from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, TypeAlias, runtime_checkable


class HistoryKind(StrEnum):
    COMMITMENT = "commitment"
    CONFLICT = "conflict"
    RELATIONSHIP_CHANGE = "relationship_change"
    PLAYER_CHOICE = "player_choice"
    OTHER = "other"


_CRITICAL_KINDS = (
    HistoryKind.COMMITMENT,
    HistoryKind.CONFLICT,
    HistoryKind.RELATIONSHIP_CHANGE,
    HistoryKind.PLAYER_CHOICE,
)
_KIND_LABELS = {
    HistoryKind.COMMITMENT: "承诺",
    HistoryKind.CONFLICT: "冲突",
    HistoryKind.RELATIONSHIP_CHANGE: "关系变化",
    HistoryKind.PLAYER_CHOICE: "玩家选择",
    HistoryKind.OTHER: "对话",
}
_KIND_ALIASES = {
    "commitment": HistoryKind.COMMITMENT,
    "promise": HistoryKind.COMMITMENT,
    "承诺": HistoryKind.COMMITMENT,
    "conflict": HistoryKind.CONFLICT,
    "冲突": HistoryKind.CONFLICT,
    "relationship": HistoryKind.RELATIONSHIP_CHANGE,
    "relationship_change": HistoryKind.RELATIONSHIP_CHANGE,
    "关系": HistoryKind.RELATIONSHIP_CHANGE,
    "关系变化": HistoryKind.RELATIONSHIP_CHANGE,
    "choice": HistoryKind.PLAYER_CHOICE,
    "player_choice": HistoryKind.PLAYER_CHOICE,
    "选择": HistoryKind.PLAYER_CHOICE,
    "玩家选择": HistoryKind.PLAYER_CHOICE,
    "other": HistoryKind.OTHER,
}
_KEYWORDS = {
    HistoryKind.COMMITMENT: (
        "承诺",
        "答应",
        "保证",
        "发誓",
        "约定",
        "promise",
        "promised",
        "pledge",
        "pledged",
        "vow",
    ),
    HistoryKind.CONFLICT: (
        "冲突",
        "争吵",
        "威胁",
        "背叛",
        "袭击",
        "敌对",
        "conflict",
        "threat",
        "betray",
        "attack",
        "quarrel",
    ),
    HistoryKind.RELATIONSHIP_CHANGE: (
        "关系变化",
        "信任增加",
        "信任下降",
        "好感",
        "原谅",
        "不再信任",
        "trust increased",
        "trust decreased",
        "affinity",
        "forgave",
        "relationship changed",
    ),
    HistoryKind.PLAYER_CHOICE: (
        "玩家选择",
        "玩家决定",
        "玩家接受",
        "玩家拒绝",
        "选择了",
        "决定了",
        "player chose",
        "player decided",
        "player accepted",
        "player refused",
    ),
}


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    text: str
    turn_id: str = ""
    kinds: tuple[HistoryKind, ...] = ()

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("History record text must not be empty")


HistoryInput: TypeAlias = str | HistoryRecord | Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CompactedHistory:
    summary: str
    retained_facts: tuple[HistoryRecord, ...]
    recent_records: tuple[HistoryRecord, ...]
    source_count: int
    dropped_count: int
    strategy: str = "deterministic-v1"

    @property
    def char_count(self) -> int:
        return len(self.summary)


@runtime_checkable
class HistoryCompactor(Protocol):
    def compact(
        self,
        history: Sequence[HistoryInput],
        *,
        recent_limit: int = 4,
        max_chars: int = 3_000,
    ) -> CompactedHistory: ...


class DeterministicHistoryCompactor:
    """Compress history while prioritizing durable gameplay facts."""

    def compact(
        self,
        history: Sequence[HistoryInput],
        *,
        recent_limit: int = 4,
        max_chars: int = 3_000,
    ) -> CompactedHistory:
        if recent_limit < 0:
            raise ValueError("recent_limit must not be negative")
        if max_chars < 1:
            raise ValueError("max_chars must be positive")

        records = _coerce_records(history)
        critical = _deduplicate(
            record for record in records if any(kind in _CRITICAL_KINDS for kind in record.kinds)
        )
        critical_keys = {_normalized_text(record.text) for record in critical}
        recent_candidates = [
            record for record in records if _normalized_text(record.text) not in critical_keys
        ]
        recent = _deduplicate(recent_candidates[-recent_limit:] if recent_limit else ())

        summary, retained_facts, retained_recent = _build_summary(
            critical,
            recent,
            max_chars=max_chars,
        )
        retained_keys = {
            (record.turn_id, _normalized_text(record.text))
            for record in (*retained_facts, *retained_recent)
        }
        dropped_count = sum(
            (record.turn_id, _normalized_text(record.text)) not in retained_keys
            for record in records
        )
        return CompactedHistory(
            summary=summary,
            retained_facts=retained_facts,
            recent_records=retained_recent,
            source_count=len(records),
            dropped_count=dropped_count,
        )


def compact_history(
    history: Sequence[HistoryInput],
    *,
    recent_limit: int = 4,
    max_chars: int = 3_000,
) -> CompactedHistory:
    return DeterministicHistoryCompactor().compact(
        history,
        recent_limit=recent_limit,
        max_chars=max_chars,
    )


def classify_history(text: str) -> tuple[HistoryKind, ...]:
    normalized = unicase(text)
    kinds = [
        kind
        for kind in _CRITICAL_KINDS
        if any(keyword in normalized for keyword in _KEYWORDS[kind])
    ]
    return tuple(kinds) or (HistoryKind.OTHER,)


def _coerce_records(history: Sequence[HistoryInput]) -> list[HistoryRecord]:
    records: list[HistoryRecord] = []
    for index, item in enumerate(history, start=1):
        if isinstance(item, HistoryRecord):
            kinds = item.kinds or classify_history(item.text)
            records.append(HistoryRecord(text=item.text.strip(), turn_id=item.turn_id, kinds=kinds))
            continue
        if isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            records.append(
                HistoryRecord(
                    text=text,
                    turn_id=f"history:{index}",
                    kinds=classify_history(text),
                )
            )
            continue
        if not isinstance(item, Mapping):
            raise TypeError(f"Unsupported history item: {type(item)!r}")

        expanded = _expand_structured_facts(item, index)
        if expanded:
            records.extend(expanded)
            continue
        text = str(item.get("text") or item.get("content") or item.get("summary") or "").strip()
        if not text:
            continue
        turn_id = str(item.get("turn_id") or item.get("id") or f"history:{index}")
        kinds = _parse_kinds(item.get("kinds") or item.get("tags") or item.get("category"))
        records.append(
            HistoryRecord(
                text=text,
                turn_id=turn_id,
                kinds=kinds or classify_history(text),
            )
        )
    return records


def _expand_structured_facts(item: Mapping[str, Any], index: int) -> list[HistoryRecord]:
    field_kinds = {
        "commitments": HistoryKind.COMMITMENT,
        "conflicts": HistoryKind.CONFLICT,
        "relationship_changes": HistoryKind.RELATIONSHIP_CHANGE,
        "player_choices": HistoryKind.PLAYER_CHOICE,
    }
    turn_id = str(item.get("turn_id") or item.get("id") or f"history:{index}")
    records: list[HistoryRecord] = []
    for field_name, kind in field_kinds.items():
        values = item.get(field_name, ())
        if isinstance(values, str):
            values = (values,)
        if not isinstance(values, Sequence):
            continue
        for value in values:
            text = str(value).strip()
            if text:
                records.append(HistoryRecord(text=text, turn_id=turn_id, kinds=(kind,)))
    return records


def _parse_kinds(raw_kinds: Any) -> tuple[HistoryKind, ...]:
    if raw_kinds is None:
        return ()
    values = (raw_kinds,) if isinstance(raw_kinds, str) else raw_kinds
    if not isinstance(values, Sequence):
        return ()
    kinds: list[HistoryKind] = []
    for value in values:
        normalized = str(value).strip().casefold()
        kind = _KIND_ALIASES.get(normalized)
        if kind is not None and kind not in kinds:
            kinds.append(kind)
    return tuple(kinds)


def _deduplicate(records: Iterable[HistoryRecord]) -> list[HistoryRecord]:
    unique: list[HistoryRecord] = []
    seen: set[str] = set()
    for record in records:
        key = _normalized_text(record.text)
        if key not in seen:
            unique.append(record)
            seen.add(key)
    return unique


def _build_summary(
    critical: Sequence[HistoryRecord],
    recent: Sequence[HistoryRecord],
    *,
    max_chars: int,
) -> tuple[str, tuple[HistoryRecord, ...], tuple[HistoryRecord, ...]]:
    lines: list[str] = []
    retained_facts: list[HistoryRecord] = []
    retained_recent: list[HistoryRecord] = []

    def append_section(
        title: str,
        records: Sequence[HistoryRecord],
        destination: list[HistoryRecord],
        *,
        include_kind: bool,
    ) -> None:
        if not records:
            return
        header = f"[{title}]"
        if not _append_line(lines, header, max_chars):
            return
        for record in records:
            labels = "/".join(
                _KIND_LABELS[kind] for kind in record.kinds if kind is not HistoryKind.OTHER
            )
            prefix = f"- ({labels}) " if include_kind and labels else "- "
            fitted = _fit_line(lines, prefix, record.text, max_chars)
            if fitted is None:
                continue
            lines.append(fitted)
            destination.append(record)

    append_section("关键事实", critical, retained_facts, include_kind=True)
    append_section("最近对话", recent, retained_recent, include_kind=False)
    return "\n".join(lines), tuple(retained_facts), tuple(retained_recent)


def _append_line(lines: list[str], line: str, max_chars: int) -> bool:
    rendered_size = sum(len(existing) for existing in lines) + max(0, len(lines) - 1)
    separator_size = 1 if lines else 0
    if rendered_size + separator_size + len(line) > max_chars:
        return False
    lines.append(line)
    return True


def _fit_line(lines: Sequence[str], prefix: str, text: str, max_chars: int) -> str | None:
    rendered_size = sum(len(line) for line in lines) + max(0, len(lines) - 1)
    remaining = max_chars - rendered_size - (1 if lines else 0)
    if remaining <= len(prefix):
        return None
    if len(prefix) + len(text) <= remaining:
        return f"{prefix}{text}"
    room = remaining - len(prefix)
    if room == 1:
        return f"{prefix}…"
    return f"{prefix}{text[: room - 1].rstrip()}…"


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", unicase(text)).strip()


def unicase(text: str) -> str:
    return text.casefold()
