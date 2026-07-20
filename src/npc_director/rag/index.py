from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[._'-][a-z0-9]+)*|[\u3400-\u4dbf\u4e00-\u9fff]+")
_SUPPORTED_SUFFIXES = {".json", ".md", ".txt"}


def tokenize(text: str) -> tuple[str, ...]:
    """Tokenize Latin text and CJK text without external dependencies."""

    normalized = unicodedata.normalize("NFKC", text).casefold()
    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(normalized):
        segment = match.group(0)
        if not segment:
            continue
        if _is_cjk(segment[0]):
            tokens.extend(segment)
            tokens.extend(segment[index : index + 2] for index in range(len(segment) - 1))
            if len(segment) <= 12:
                tokens.append(segment)
        else:
            tokens.append(segment)
    return tuple(tokens)


def _is_cjk(character: str) -> bool:
    return "\u3400" <= character <= "\u4dbf" or "\u4e00" <= character <= "\u9fff"


def scope_is_allowed(scope: str, allowed_scopes: Iterable[str]) -> bool:
    """Return whether an exact or explicitly granted parent scope permits a document."""

    normalized_scope = scope.strip().casefold()
    for allowed in allowed_scopes:
        normalized_allowed = allowed.strip().casefold().rstrip(":/")
        if not normalized_allowed:
            continue
        if normalized_scope == normalized_allowed:
            return True
        if normalized_scope.startswith(f"{normalized_allowed}:"):
            return True
        if normalized_scope.startswith(f"{normalized_allowed}/"):
            return True
    return False


@dataclass(frozen=True, slots=True)
class LoreDocument:
    ref: str
    text: str
    scope: str = "public"
    title: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.ref.strip():
            raise ValueError("Lore document ref must not be empty")
        if not self.text.strip():
            raise ValueError("Lore document text must not be empty")
        if not self.scope.strip():
            raise ValueError("Lore document scope must not be empty")


@dataclass(frozen=True, slots=True)
class LoreSearchHit:
    document: LoreDocument
    score: float
    matched_terms: tuple[str, ...]

    @property
    def ref(self) -> str:
        return self.document.ref

    @property
    def scope(self) -> str:
        return self.document.scope


@dataclass(frozen=True, slots=True)
class _IndexedDocument:
    document: LoreDocument
    terms: Counter[str]
    length: int


class LexicalLoreIndex:
    """A deterministic in-memory BM25 index with scope filtering."""

    def __init__(
        self,
        documents: Iterable[LoreDocument] = (),
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        if k1 <= 0:
            raise ValueError("k1 must be positive")
        if not 0 <= b <= 1:
            raise ValueError("b must be between 0 and 1")
        self._k1 = k1
        self._b = b
        self._documents: tuple[_IndexedDocument, ...] = ()
        self._version = "empty"
        self.replace_documents(documents)

    @classmethod
    def from_directory(cls, root: str | Path) -> LexicalLoreIndex:
        return cls(load_lore_documents(root))

    @property
    def documents(self) -> tuple[LoreDocument, ...]:
        return tuple(indexed.document for indexed in self._documents)

    @property
    def version(self) -> str:
        return self._version

    def replace_documents(self, documents: Iterable[LoreDocument]) -> None:
        ordered = sorted(documents, key=lambda document: document.ref)
        refs = [document.ref for document in ordered]
        if len(refs) != len(set(refs)):
            raise ValueError("Lore document refs must be unique")

        indexed_documents: list[_IndexedDocument] = []
        fingerprint = sha256()
        for document in ordered:
            tags = document.metadata.get("tags", ())
            tag_text = tags if isinstance(tags, str) else " ".join(str(tag) for tag in tags)
            terms = Counter(tokenize(f"{document.title} {tag_text} {document.text}"))
            indexed_documents.append(
                _IndexedDocument(
                    document=document,
                    terms=terms,
                    length=sum(terms.values()),
                )
            )
            fingerprint.update(document.ref.encode())
            fingerprint.update(b"\0")
            fingerprint.update(document.scope.encode())
            fingerprint.update(b"\0")
            fingerprint.update(document.title.encode())
            fingerprint.update(b"\0")
            fingerprint.update(document.text.encode())
            fingerprint.update(b"\0")

        self._documents = tuple(indexed_documents)
        self._version = fingerprint.hexdigest()[:20] if indexed_documents else "empty"

    def search(
        self,
        query: str,
        *,
        allowed_scopes: Iterable[str] = ("public",),
        top_k: int = 4,
    ) -> tuple[LoreSearchHit, ...]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        tokenized_query = tokenize(query)
        has_multi_character_cjk = any(
            len(term) > 1 and _is_cjk(term[0]) for term in tokenized_query
        )
        query_terms = Counter(
            term
            for term in tokenized_query
            if not (has_multi_character_cjk and len(term) == 1 and _is_cjk(term))
        )
        if not query_terms or not self._documents:
            return ()

        allowed_documents = [
            indexed
            for indexed in self._documents
            if scope_is_allowed(indexed.document.scope, allowed_scopes)
        ]
        if not allowed_documents:
            return ()
        document_count = len(allowed_documents)
        average_length = sum(document.length for document in allowed_documents) / document_count
        scoped_document_frequency = {
            term: sum(term in indexed.terms for indexed in allowed_documents)
            for term in query_terms
        }
        hits: list[LoreSearchHit] = []
        for indexed in allowed_documents:
            score = 0.0
            matched_terms: list[str] = []
            for term, query_frequency in query_terms.items():
                term_frequency = indexed.terms.get(term, 0)
                if term_frequency == 0:
                    continue
                matched_terms.append(term)
                document_frequency = scoped_document_frequency[term]
                inverse_document_frequency = math.log(
                    1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                length_ratio = indexed.length / average_length if average_length else 0
                denominator = term_frequency + self._k1 * (1 - self._b + self._b * length_ratio)
                query_weight = 1 + math.log(query_frequency)
                score += (
                    inverse_document_frequency
                    * (term_frequency * (self._k1 + 1) / denominator)
                    * query_weight
                )
            if score > 0:
                hits.append(
                    LoreSearchHit(
                        document=indexed.document,
                        score=score,
                        matched_terms=tuple(sorted(set(matched_terms))),
                    )
                )

        hits.sort(key=lambda hit: (-hit.score, hit.ref))
        return tuple(hits[:top_k])


def load_lore_documents(root: str | Path) -> tuple[LoreDocument, ...]:
    root_path = Path(root)
    if not root_path.exists():
        raise FileNotFoundError(root_path)
    documents = [
        _load_lore_document(path, root_path)
        for path in sorted(root_path.rglob("*"))
        if path.is_file() and path.suffix.casefold() in _SUPPORTED_SUFFIXES
    ]
    return tuple(documents)


def _load_lore_document(path: Path, root: Path) -> LoreDocument:
    relative = path.relative_to(root)
    path_scope = _scope_from_path(relative)
    if path.suffix.casefold() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Lore JSON must contain an object: {path}")
        document_id = str(raw.get("ref") or raw.get("id") or relative.with_suffix(""))
        ref = document_id if ":" in document_id else f"lore:{document_id}"
        text = str(raw.get("content") or raw.get("text") or "")
        title = str(raw.get("title") or "")
        declared_scope = str(raw.get("scope") or path_scope)
        scope = _validated_scope(path_scope, declared_scope, path)
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError(f"Lore metadata must contain an object: {path}")
        if "tags" in raw:
            metadata = {**metadata, "tags": raw["tags"]}
        return LoreDocument(ref=ref, text=text, scope=scope, title=title, metadata=metadata)

    content = path.read_text(encoding="utf-8")
    frontmatter, text = _split_frontmatter(content)
    document_id = frontmatter.get("ref") or frontmatter.get("id") or str(relative.with_suffix(""))
    ref = document_id if ":" in document_id else f"lore:{document_id}"
    scope = _validated_scope(path_scope, frontmatter.get("scope", path_scope), path)
    return LoreDocument(
        ref=ref,
        text=text,
        scope=scope,
        title=frontmatter.get("title", ""),
        metadata={},
    )


def _scope_from_path(relative: Path) -> str:
    parent_parts = relative.parent.parts
    if not parent_parts or parent_parts == (".",):
        return "public"
    root_scope = parent_parts[0].casefold()
    if root_scope == "secret" and len(parent_parts) > 1:
        return ":".join((root_scope, *parent_parts[1:]))
    return root_scope


def _validated_scope(path_scope: str, declared_scope: str, path: Path) -> str:
    normalized_path_scope = path_scope.casefold()
    normalized_declared_scope = declared_scope.strip().casefold()
    if normalized_path_scope.startswith("secret") and not (
        normalized_declared_scope == normalized_path_scope
        or normalized_declared_scope.startswith(f"{normalized_path_scope}:")
        or normalized_declared_scope.startswith(f"{normalized_path_scope}/")
    ):
        raise ValueError(f"Secret lore scope must stay within its path scope: {path}")
    return declared_scope.strip()


def _split_frontmatter(content: str) -> tuple[dict[str, str], str]:
    if not content.startswith("---\n"):
        return {}, content.strip()
    marker = content.find("\n---\n", 4)
    if marker < 0:
        return {}, content.strip()
    metadata: dict[str, str] = {}
    for line in content[4:marker].splitlines():
        key, separator, value = line.partition(":")
        if separator:
            metadata[key.strip().casefold()] = value.strip()
    return metadata, content[marker + 5 :].strip()
