from __future__ import annotations

import json

import pytest
from agents import Agent
from agents.exceptions import ModelBehaviorError

from npc_director.config import Settings
from npc_director.contracts import DialogueDraft, NarrativePlan
from npc_director.contracts.planning import OperationRequest, TurnAnalysis
from npc_director.orchestration.bounded_executor import BoundedDirectorExecutor, TypedModelCall
from tests.test_bounded_executor import ROUTER, WRITER, dialogue, director_input, narrative
from tests.test_dynamic_planning import make_executor, successful_outputs


@pytest.mark.asyncio
async def test_unknown_operation_dependency_is_repaired_before_any_downstream_call():
    invalid = TurnAnalysis(
        intent="other",
        objective="核实已知信息",
        operations=[OperationRequest(id="plan", kind="narrative", depends_on=["missing"])],
    )
    corrected = TurnAnalysis(intent="other", objective="根据已有信息答复")
    outputs = successful_outputs(corrected)
    outputs[ROUTER] = [invalid, corrected]
    executor, calls = make_executor(outputs)
    result = await executor.generate(director_input())
    assert result.execution_trace.stop_reason == "completed"
    assert result.execution_trace.repairs == 1
    assert [agent for agent, _, _ in calls][:3] == [ROUTER, ROUTER, WRITER]
    assert result.execution_trace.analysis == corrected
    assert "unknown dependency" in calls[1][1]


@pytest.mark.asyncio
async def test_graph_repair_is_bounded_and_never_runs_an_invalid_plan():
    invalid = TurnAnalysis(
        intent="other",
        objective="等待核实",
        operations=[OperationRequest(id="plan", kind="narrative", depends_on=["plan"])],
    )
    executor, calls = make_executor({ROUTER: invalid})
    result = await executor.generate(director_input())
    assert result.execution_trace.stop_reason == "invalid_plan"
    assert len(calls) == 2
    assert result.proposal.plan.proposed_state_changes.quests == []


@pytest.mark.asyncio
async def test_native_decode_failure_repairs_only_failed_node_with_strict_prompt_contract():
    calls = []

    async def runner(agent, payload, output_type):
        calls.append((agent, output_type))
        if output_type is TurnAnalysis:
            output = TurnAnalysis(intent="greeting", objective="回应问候")
        elif output_type is DialogueDraft:
            if sum(kind is DialogueDraft for _, kind in calls) == 1:
                raise ModelBehaviorError("invalid JSON from native decoder")
            assert agent.output_type is None
            assert "OUTPUT CONTRACT JSON SCHEMA:" in agent.instructions
            output = dialogue()
        else:
            from npc_director.contracts import PerformanceOutput
            from tests.test_dynamic_planning import PERFORMANCE, QUALITY

            output = successful_outputs(TurnAnalysis(intent="greeting", objective="回应问候"))[
                PERFORMANCE if output_type is PerformanceOutput else QUALITY
            ]
        return TypedModelCall(output=output)

    executor = BoundedDirectorExecutor(Settings(model="gpt-test"), typed_runner=runner)
    result = await executor.generate(director_input())
    assert result.execution_trace.stop_reason == "completed"
    assert sum(kind is TurnAnalysis for _, kind in calls) == 1
    assert sum(kind is DialogueDraft for _, kind in calls) == 2


@pytest.mark.asyncio
async def test_nested_narrative_uses_prompt_json_with_same_runtime_output_type():
    from npc_director.orchestration.bounded_executor import _UsageTotals

    async def runner(agent, payload, output_type):
        assert agent.output_type is None
        schema = agent.instructions.split("OUTPUT CONTRACT JSON SCHEMA:\n")[1]
        assert json.loads(schema)["title"] == "NarrativePlan"
        assert output_type is NarrativePlan
        return TypedModelCall(output=narrative())

    executor = BoundedDirectorExecutor(Settings(model="gpt-test"), typed_runner=runner)
    output, _ = await executor._run_typed(
        Agent(name="Narrative", instructions="Plan the scene.", output_type=NarrativePlan),
        "{}",
        NarrativePlan,
        _UsageTotals(),
    )
    assert isinstance(output, NarrativePlan)
