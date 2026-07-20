from __future__ import annotations

from agents import Agent, RunContextWrapper, function_tool

from npc_director.agents.specialists._shared import build_specialist_agent
from npc_director.config import Settings
from npc_director.contracts import LoreEvidence
from npc_director.runtime import AgentRuntimeDependencies

LORE_PROMPT_VERSION = "lore-v1"

LORE_INSTRUCTIONS = """
你是 NPC Director 的 Lore Specialist，只负责返回可追溯的世界观证据。

严格规则：
1. 输入只包含 LoreInput 的结构化字段；不得索取角色私有记忆、完整数据库或玩家原话。
2. 只输出 LoreEvidence，不创作 NPC 台词、剧情决定、状态修改或演出参数。
3. 必须调用 search_lore 检索证据；只能使用工具返回且属于 allowed_scopes 的事实。
4. 每条 evidence 必须有稳定 ref、原意一致的 excerpt、允许的 scope 和保守 score。
5. 没有足够证据时不得补全或猜测，把对应查询放入 unanswered_queries。
6. max_results 是硬上限；秘密或越权信息不得作为证据返回。
""".strip()


@function_tool
async def search_lore(
    context: RunContextWrapper[AgentRuntimeDependencies],
    query: str,
    allowed_scopes: list[str],
    max_results: int = 4,
) -> LoreEvidence:
    """Search authorized game lore and return stable citations."""
    dependencies = context.context
    if dependencies.lore_retriever is None:
        return LoreEvidence(items=[], unanswered_queries=[query])
    authorized_scopes = tuple(
        scope for scope in allowed_scopes if scope in set(dependencies.allowed_lore_scopes)
    )
    if not authorized_scopes:
        return LoreEvidence(items=[], unanswered_queries=[query])
    result = dependencies.lore_retriever.retrieve(
        query,
        allowed_scopes=authorized_scopes,
        top_k=min(max_results, dependencies.lore_budget.top_k),
        token_budget=dependencies.lore_budget.max_tokens,
        char_budget=dependencies.lore_budget.max_chars,
    )
    dependencies.accessed_lore_refs.update(item.ref for item in result.items)
    return result.to_contract()


def build_lore_specialist_agent(settings: Settings | None = None) -> Agent[None]:
    return build_specialist_agent(
        name="Lore Specialist",
        role="lore",
        instructions=LORE_INSTRUCTIONS,
        output_type=LoreEvidence,
        settings=settings,
        tools=[search_lore],
    )
