from __future__ import annotations

from dataclasses import dataclass, field

from npc_director.rag import LoreRetriever, RetrievalBudget


@dataclass(slots=True)
class AgentRuntimeDependencies:
    lore_retriever: LoreRetriever | None = None
    allowed_lore_scopes: tuple[str, ...] = ("public",)
    lore_budget: RetrievalBudget = field(default_factory=RetrievalBudget)
    accessed_lore_refs: set[str] = field(default_factory=set)
