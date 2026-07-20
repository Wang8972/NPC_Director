from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Callable, Collection, Hashable, Sequence
from dataclasses import dataclass, replace
from typing import Generic, Protocol, TypeVar, runtime_checkable

from npc_director.contracts.specialists import LoreEvidence, LoreEvidenceItem
from npc_director.rag.index import LexicalLoreIndex, LoreSearchHit

_ESTIMATED_TOKEN_PATTERN = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff]|[a-zA-Z0-9_]+|[^\s]",
)


def estimate_tokens(text: str) -> int:
    """Return a deterministic, conservative token estimate for mixed text."""

    count = 0
    for match in _ESTIMATED_TOKEN_PATTERN.finditer(text):
        segment = match.group(0)
        if segment.isascii() and (segment.isalnum() or "_" in segment):
            count += max(1, math.ceil(len(segment) / 4))
        else:
            count += 1
    return count


@dataclass(frozen=True, slots=True)
class RetrievalBudget:
    top_k: int = 4
    max_tokens: int = 1_200
    max_chars: int = 4_800

    def __post_init__(self) -> None:
        if self.top_k < 1:
            raise ValueError("top_k must be positive")
        if self.max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if self.max_chars < 1:
            raise ValueError("max_chars must be positive")


@dataclass(frozen=True, slots=True)
class RetrievedLoreItem:
    ref: str
    excerpt: str
    scope: str
    score: float
    queries: tuple[str, ...] = ()

    def to_contract(self) -> LoreEvidenceItem:
        return LoreEvidenceItem(
            ref=self.ref,
            excerpt=self.excerpt,
            scope=self.scope,
            score=self.score,
        )


@dataclass(frozen=True, slots=True)
class LoreRetrievalResult:
    items: tuple[RetrievedLoreItem, ...]
    unanswered_queries: tuple[str, ...]
    used_tokens: int
    used_chars: int
    truncated: bool = False
    cache_hit: bool = False

    def render(self) -> str:
        return "\n".join(f"[{item.ref}] {item.excerpt}" for item in self.items)

    def to_contract(self) -> LoreEvidence:
        return LoreEvidence(
            items=[item.to_contract() for item in self.items[:8]],
            unanswered_queries=list(self.unanswered_queries[:4]),
        )


@runtime_checkable
class LoreRetriever(Protocol):
    """Replaceable boundary for local, hosted, or hybrid lore retrieval."""

    def retrieve(
        self,
        queries: str | Sequence[str],
        *,
        allowed_scopes: Collection[str] = ("public",),
        top_k: int = 4,
        token_budget: int = 1_200,
        char_budget: int = 4_800,
    ) -> LoreRetrievalResult: ...


@dataclass(slots=True)
class _Candidate:
    hit: LoreSearchHit
    queries: list[str]


class LexicalLoreRetriever:
    """JIT retriever that applies permissions before ranking and budgeting."""

    def __init__(self, index: LexicalLoreIndex) -> None:
        self._index = index

    @property
    def revision(self) -> str:
        return self._index.version

    def retrieve(
        self,
        queries: str | Sequence[str],
        *,
        allowed_scopes: Collection[str] = ("public",),
        top_k: int = 4,
        token_budget: int = 1_200,
        char_budget: int = 4_800,
    ) -> LoreRetrievalResult:
        budget = RetrievalBudget(
            top_k=top_k,
            max_tokens=token_budget,
            max_chars=char_budget,
        )
        normalized_queries = _normalize_queries(queries)
        if not normalized_queries:
            return LoreRetrievalResult((), (), 0, 0)

        candidate_by_ref: dict[str, _Candidate] = {}
        unanswered_queries: list[str] = []
        for query in normalized_queries:
            hits = self._index.search(
                query,
                allowed_scopes=allowed_scopes,
                top_k=budget.top_k,
            )
            if not hits:
                unanswered_queries.append(query)
                continue
            for hit in hits:
                candidate = candidate_by_ref.get(hit.ref)
                if candidate is None:
                    candidate_by_ref[hit.ref] = _Candidate(hit=hit, queries=[query])
                    continue
                if hit.score > candidate.hit.score:
                    candidate.hit = hit
                if query not in candidate.queries:
                    candidate.queries.append(query)

        candidates = sorted(
            candidate_by_ref.values(),
            key=lambda candidate: (-candidate.hit.score, candidate.hit.ref),
        )
        selected: list[RetrievedLoreItem] = []
        truncated = len(candidates) > budget.top_k
        for candidate in candidates[: budget.top_k]:
            excerpt = _select_excerpt(candidate.hit, candidate.queries)
            fitted_excerpt = _fit_excerpt(
                selected,
                candidate.hit.ref,
                excerpt,
                budget,
            )
            if not fitted_excerpt:
                truncated = True
                continue
            if fitted_excerpt != excerpt:
                truncated = True
            selected.append(
                RetrievedLoreItem(
                    ref=candidate.hit.ref,
                    excerpt=fitted_excerpt,
                    scope=candidate.hit.scope,
                    score=_bounded_score(candidate.hit.score),
                    queries=tuple(candidate.queries),
                )
            )

        covered_queries = {query for item in selected for query in item.queries}
        unanswered_queries.extend(
            query
            for query in normalized_queries
            if query not in covered_queries and query not in unanswered_queries
        )
        rendered = _render_items(selected)
        return LoreRetrievalResult(
            items=tuple(selected),
            unanswered_queries=tuple(unanswered_queries),
            used_tokens=estimate_tokens(rendered),
            used_chars=len(rendered),
            truncated=truncated,
        )


CacheKey = TypeVar("CacheKey", bound=Hashable)
CacheValue = TypeVar("CacheValue")


@dataclass(slots=True)
class _CacheEntry(Generic[CacheValue]):
    expires_at: float
    value: CacheValue


class TTLCache(Generic[CacheKey, CacheValue]):
    def __init__(
        self,
        *,
        ttl_seconds: float = 60.0,
        max_entries: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: dict[CacheKey, _CacheEntry[CacheValue]] = {}
        self._lock = threading.RLock()

    def get(self, key: CacheKey) -> tuple[bool, CacheValue | None]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False, None
            if entry.expires_at <= self._clock():
                del self._entries[key]
                return False, None
            return True, entry.value

    def set(self, key: CacheKey, value: CacheValue) -> None:
        with self._lock:
            now = self._clock()
            self._remove_expired(now)
            if key not in self._entries and len(self._entries) >= self._max_entries:
                oldest_key = min(
                    self._entries,
                    key=lambda existing_key: self._entries[existing_key].expires_at,
                )
                del self._entries[oldest_key]
            self._entries[key] = _CacheEntry(
                expires_at=now + self._ttl_seconds,
                value=value,
            )

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            self._remove_expired(self._clock())
            return len(self._entries)

    def _remove_expired(self, now: float) -> None:
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            del self._entries[key]


@dataclass(frozen=True, slots=True)
class CacheStats:
    hits: int
    misses: int


class CachedLoreRetriever:
    def __init__(
        self,
        retriever: LoreRetriever,
        *,
        ttl_seconds: float = 60.0,
        max_entries: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._retriever = retriever
        self._cache: TTLCache[tuple[object, ...], LoreRetrievalResult] = TTLCache(
            ttl_seconds=ttl_seconds,
            max_entries=max_entries,
            clock=clock,
        )
        self._hits = 0
        self._misses = 0
        self._stats_lock = threading.Lock()

    @property
    def revision(self) -> str:
        return str(getattr(self._retriever, "revision", "unversioned"))

    @property
    def stats(self) -> CacheStats:
        with self._stats_lock:
            return CacheStats(hits=self._hits, misses=self._misses)

    def retrieve(
        self,
        queries: str | Sequence[str],
        *,
        allowed_scopes: Collection[str] = ("public",),
        top_k: int = 4,
        token_budget: int = 1_200,
        char_budget: int = 4_800,
    ) -> LoreRetrievalResult:
        normalized_queries = _normalize_queries(queries)
        cache_key: tuple[object, ...] = (
            self.revision,
            normalized_queries,
            tuple(sorted(scope.strip().casefold() for scope in allowed_scopes)),
            top_k,
            token_budget,
            char_budget,
        )
        found, cached = self._cache.get(cache_key)
        if found and cached is not None:
            with self._stats_lock:
                self._hits += 1
            return replace(cached, cache_hit=True)

        result = self._retriever.retrieve(
            normalized_queries,
            allowed_scopes=allowed_scopes,
            top_k=top_k,
            token_budget=token_budget,
            char_budget=char_budget,
        )
        uncached_result = replace(result, cache_hit=False)
        self._cache.set(cache_key, uncached_result)
        with self._stats_lock:
            self._misses += 1
        return uncached_result


def _normalize_queries(queries: str | Sequence[str]) -> tuple[str, ...]:
    values = (queries,) if isinstance(queries, str) else queries
    normalized: list[str] = []
    seen: set[str] = set()
    for query in values:
        cleaned = " ".join(str(query).split())
        key = cleaned.casefold()
        if cleaned and key not in seen:
            normalized.append(cleaned)
            seen.add(key)
    return tuple(normalized)


def _bounded_score(score: float) -> float:
    return min(1.0, max(0.0, 1 - math.exp(-score)))


def _select_excerpt(hit: LoreSearchHit, queries: Sequence[str], max_chars: int = 1_000) -> str:
    text = " ".join(hit.document.text.split())
    if len(text) <= max_chars:
        return text

    folded = text.casefold()
    anchors = [query.casefold() for query in queries]
    anchors.extend(term for term in hit.matched_terms if len(term) > 1)
    positions = [folded.find(anchor) for anchor in anchors if anchor and folded.find(anchor) >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - max_chars // 4)
    has_prefix = start > 0
    content_budget = max_chars - int(has_prefix) - 1
    end = min(len(text), start + content_budget)
    has_suffix = end < len(text)
    if not has_suffix:
        end = min(len(text), end + 1)
    excerpt = text[start:end].strip()
    return f"{'…' if has_prefix else ''}{excerpt}{'…' if has_suffix else ''}"


def _fit_excerpt(
    existing_items: Sequence[RetrievedLoreItem],
    ref: str,
    excerpt: str,
    budget: RetrievalBudget,
) -> str:
    def fits(candidate_excerpt: str) -> bool:
        provisional = [
            *existing_items,
            RetrievedLoreItem(ref=ref, excerpt=candidate_excerpt, scope="", score=0),
        ]
        rendered = _render_items(provisional)
        return len(rendered) <= budget.max_chars and estimate_tokens(rendered) <= budget.max_tokens

    if fits(excerpt):
        return excerpt
    lower = 0
    upper = len(excerpt)
    best = ""
    while lower <= upper:
        midpoint = (lower + upper) // 2
        candidate = _truncate_excerpt(excerpt, midpoint)
        if candidate and fits(candidate):
            best = candidate
            lower = midpoint + 1
        else:
            upper = midpoint - 1
    return best


def _truncate_excerpt(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit == 1:
        return "…"
    prefix = text[: limit - 1].rstrip()
    if " " in prefix:
        boundary = prefix.rfind(" ")
        if boundary >= max(1, len(prefix) // 2):
            prefix = prefix[:boundary].rstrip()
    return f"{prefix}…" if prefix else "…"


def _render_items(items: Sequence[RetrievedLoreItem]) -> str:
    return "\n".join(f"[{item.ref}] {item.excerpt}" for item in items)
