from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Protocol, runtime_checkable

from npc_director.context.compaction import (
    CompactedHistory,
    DeterministicHistoryCompactor,
    HistoryInput,
    HistoryKind,
    HistoryRecord,
)


@dataclass(frozen=True, slots=True)
class LongTermMemory:
    memory_id: str
    npc_id: str
    content: str
    kinds: tuple[HistoryKind, ...]
    source_session_id: str
    source_turn_ids: tuple[str, ...] = ()
    importance: float = 0.8


@dataclass(frozen=True, slots=True)
class MemoryDistillationRequest:
    session_id: str
    npc_id: str
    history: Sequence[HistoryInput] | CompactedHistory
    existing_memories: tuple[LongTermMemory, ...] = ()
    max_memories: int = 20

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")
        if not self.npc_id.strip():
            raise ValueError("npc_id must not be empty")
        if self.max_memories < 1:
            raise ValueError("max_memories must be positive")


@dataclass(frozen=True, slots=True)
class MemoryDistillationResult:
    memories: tuple[LongTermMemory, ...]
    strategy: str
    skipped_count: int = 0
    fallback_used: bool = False
    fallback_reason: str | None = None


@runtime_checkable
class LongTermMemoryDistiller(Protocol):
    """Replaceable boundary for model-backed or deterministic distillation."""

    def distill(self, request: MemoryDistillationRequest) -> MemoryDistillationResult: ...


class DeterministicMemoryDistiller:
    """Extract only durable, explicitly observable facts without an LLM."""

    strategy = "deterministic-v1"

    def __init__(self, compactor: DeterministicHistoryCompactor | None = None) -> None:
        self._compactor = compactor or DeterministicHistoryCompactor()

    def distill(self, request: MemoryDistillationRequest) -> MemoryDistillationResult:
        compacted = (
            request.history
            if isinstance(request.history, CompactedHistory)
            else self._compactor.compact(
                request.history,
                recent_limit=0,
                max_chars=12_000,
            )
        )
        existing_content = {
            _normalize(memory.content)
            for memory in request.existing_memories
            if memory.npc_id == request.npc_id and memory.source_session_id == request.session_id
        }
        grouped: dict[str, list[HistoryRecord]] = {}
        for fact in compacted.retained_facts:
            if not _durable_kinds(fact):
                continue
            grouped.setdefault(_normalize(fact.text), []).append(fact)

        memories: list[LongTermMemory] = []
        skipped_count = 0
        for normalized_content, facts in grouped.items():
            if normalized_content in existing_content:
                skipped_count += 1
                continue
            first = facts[0]
            kinds = _ordered_kinds(kind for fact in facts for kind in fact.kinds)
            source_turn_ids = tuple(dict.fromkeys(fact.turn_id for fact in facts if fact.turn_id))
            memories.append(
                LongTermMemory(
                    memory_id=_memory_id(
                        request.npc_id, normalized_content, session_id=request.session_id
                    ),
                    npc_id=request.npc_id,
                    content=first.text.strip(),
                    kinds=kinds,
                    source_session_id=request.session_id,
                    source_turn_ids=source_turn_ids,
                    importance=max(_importance(kind) for kind in kinds),
                )
            )

        memories.sort(key=lambda memory: (-memory.importance, memory.memory_id))
        if len(memories) > request.max_memories:
            skipped_count += len(memories) - request.max_memories
            memories = memories[: request.max_memories]
        return MemoryDistillationResult(
            memories=tuple(memories),
            strategy=self.strategy,
            skipped_count=skipped_count,
        )


class MemoryDistillationService:
    """Use a primary distiller when available and fail closed to deterministic extraction."""

    def __init__(
        self,
        primary: LongTermMemoryDistiller | None = None,
        *,
        fallback: LongTermMemoryDistiller | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback or DeterministicMemoryDistiller()

    def distill(self, request: MemoryDistillationRequest) -> MemoryDistillationResult:
        if self._primary is None:
            return replace(self._fallback.distill(request), fallback_used=True)
        try:
            result = self._primary.distill(request)
            if not isinstance(result, MemoryDistillationResult):
                raise TypeError("Primary distiller returned an invalid result")
            return result
        except Exception as error:
            fallback_result = self._fallback.distill(request)
            return replace(
                fallback_result,
                fallback_used=True,
                fallback_reason=type(error).__name__,
            )

    async def distill_async(
        self,
        request: MemoryDistillationRequest,
    ) -> MemoryDistillationResult:
        """Run session-end distillation outside the interactive turn path."""

        return await asyncio.to_thread(self.distill, request)


def distill_memories(
    history: Sequence[HistoryInput] | CompactedHistory,
    *,
    session_id: str,
    npc_id: str,
    existing_memories: Sequence[LongTermMemory] = (),
    max_memories: int = 20,
) -> MemoryDistillationResult:
    request = MemoryDistillationRequest(
        session_id=session_id,
        npc_id=npc_id,
        history=history,
        existing_memories=tuple(existing_memories),
        max_memories=max_memories,
    )
    return DeterministicMemoryDistiller().distill(request)


def _durable_kinds(record: HistoryRecord) -> tuple[HistoryKind, ...]:
    return tuple(kind for kind in record.kinds if kind is not HistoryKind.OTHER)


def _ordered_kinds(kinds: Iterable[HistoryKind]) -> tuple[HistoryKind, ...]:
    seen = set(kinds)
    return tuple(
        kind
        for kind in (
            HistoryKind.COMMITMENT,
            HistoryKind.CONFLICT,
            HistoryKind.RELATIONSHIP_CHANGE,
            HistoryKind.PLAYER_CHOICE,
        )
        if kind in seen
    )


def _importance(kind: HistoryKind) -> float:
    return {
        HistoryKind.COMMITMENT: 0.9,
        HistoryKind.CONFLICT: 0.95,
        HistoryKind.RELATIONSHIP_CHANGE: 0.85,
        HistoryKind.PLAYER_CHOICE: 0.9,
    }.get(kind, 0.5)


def _memory_id(npc_id: str, normalized_content: str, *, session_id: str | None = None) -> str:
    namespace = "legacy" if session_id is None else f"session:{session_id}"
    digest = sha256(f"{namespace}\0{npc_id}\0{normalized_content}".encode()).hexdigest()[:20]
    return f"memory:{digest}"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()
