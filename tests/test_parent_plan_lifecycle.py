from __future__ import annotations

import pytest

from npc_director.config import Settings
from npc_director.contracts import EngineEvent, NPCDomainState
from npc_director.contracts.content import ObjectiveEvent, ObjectiveRef, ObjectiveStep
from npc_director.contracts.planning import ExecutionTrace, QualityVerdict
from npc_director.orchestration.service import build_default_service
from npc_director.unity_adapter.base import build_idempotency_key
from tests.test_episode_service import Adapter, complete, make_service, request


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted", [False, True])
async def test_parent_plans_commit_with_delivery_and_survive_dialogue_window(tmp_path, interrupted):
    service, fixture = make_service(tmp_path)
    parent = ObjectiveRef(objective_id="herbalist_escort", quest_id="herbalist_escort")
    service.domain_store.create(
        NPCDomainState(npc_id="elder_maren", quests={parent.key: "active"}),
        session_id="session-v2",
    )

    class PlanOnce:
        async def generate(self, source, *, repair_feedback=None):
            result = await fixture.generate(source)
            if len(fixture.inputs) == 1:
                result.objective_steps = [
                    ObjectiveStep(
                        step_id="ask-terms",
                        objective=parent,
                        description="先问清岗哨条件",
                        action="dialogue",
                        completion_condition="收到明确条件",
                    )
                ]
                result.objective_events = [
                    ObjectiveEvent(
                        event_id="route-choice",
                        objective=parent,
                        description="先谈判，失败时使用已知小路",
                        choices=["谈判", "小路"],
                        consequences=["继续原有护送目标"],
                    )
                ]
                result.execution_trace = ExecutionTrace(
                    quality=QualityVerdict(
                        passed=True, naturalness=4, persona_consistency=4, response_coverage=4
                    )
                )
            return result

    service.executor = PlanOnce()
    adapter = Adapter()
    await service.run_turn(request(text="先谈判，绕行备用。"), adapter=adapter)
    store = service.episodes.content_store
    args = ("session-v2", "elder_maren")
    assert store.list_objective_plans(*args, parent_refs=[parent]) == []
    if interrupted:
        directive = adapter.directives[0]
        await service.process_engine_event(
            EngineEvent(
                session_id=directive.session_id,
                turn_id=directive.turn_id,
                idempotency_key=build_idempotency_key(directive),
                event_type="interrupted",
            )
        )
        assert store.list_objective_plans(*args, parent_refs=[parent]) == []
        return
    await complete(service, adapter.directives[0])
    await complete(service, adapter.directives[0])
    plan = store.list_objective_plans(*args, parent_refs=[parent])[0]
    assert len(plan["steps"]) == len(plan["events"]) == 1
    assert plan["source_turn_id"] == adapter.directives[0].turn_id
    assert store.list_objective_plans("other-game", "elder_maren", parent_refs=[parent]) == []
    assert store.list_objective_plans("session-v2", "village_guard", parent_refs=[parent]) == []
    assert store.list_quests("session-v2") == []
    for index in range(7):
        await service.run_turn(request(turn=f"later-{index}", text="继续聊聊。"), adapter=adapter)
        await complete(service, adapter.directives[-1])
    restored = build_default_service(Settings(database_path=tmp_path / "state.db"))
    state = restored.domain_store.get("elder_maren", session_id="session-v2")
    incoming = request(turn="after-restart")
    # Decorate an actual episode-linked request using the restored service.
    restored.executor = fixture
    await restored.run_turn(incoming, adapter=adapter)
    assert state is not None
    remembered = fixture.inputs[-1].actor_context["objective_plans"][0]
    assert remembered["events"][0]["choices"] == ["谈判", "小路"]
    assert "先谈判，绕行备用。" not in " ".join(fixture.inputs[-1].actor_context["recent_dialogue"])
