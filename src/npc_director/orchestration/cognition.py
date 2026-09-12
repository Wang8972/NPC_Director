"""Bounded mode selection reuses the Planner; it never grants capabilities."""

from __future__ import annotations

from npc_director.contracts.cognition import BehaviorState, default_modes


class BehaviorDecisionRejected(ValueError):
    """Reject a proposed mode without granting authority or erasing the old mode."""


def mode_catalog(profile):
    modes = profile.behavior_modes or default_modes()
    result = {mode.mode_id: mode for mode in modes}
    if len(result) != len(modes) or profile.initial_behavior_mode not in result:
        raise ValueError("behavior modes must be unique and contain the initial mode")
    return [mode.model_dump(mode="json") for mode in modes]


def preview_behavior(source, analysis):
    cognition = source.actor_context.get("cognition")
    if not cognition:
        if analysis.behavior_decision is not None:
            raise ValueError("behavior decision requires enabled cognition")
        return source
    state = BehaviorState.model_validate(cognition["behavior"])
    modes = {m["mode_id"]: m for m in cognition["mode_catalog"]}
    decision = analysis.behavior_decision
    aliases = cognition.get("evidence_aliases", {})
    if decision:
        decision.evidence_refs = [aliases.get(ref, ref) for ref in decision.evidence_refs]
    analysis.used_memory_refs = [aliases.get(ref, ref) for ref in analysis.used_memory_refs]
    if decision:
        if decision.mode_id not in modes:
            raise BehaviorDecisionRejected("Planner selected an unregistered behavior mode")
        visible = set(cognition["visible_event_ids"])
        visible.update(m["memory_id"] for m in cognition["recalled_memories"])
        visible.update(eid for m in cognition["recalled_memories"] for eid in m["source_event_ids"])
        visible.update(x["content_id"] for x in source.actor_context.get("known_claims", []))
        if decision.mode_id == state.mode_id and decision.reason_code == "continue":
            # Continuing the existing state creates no new authority or transition.
            decision.evidence_refs = [ref for ref in decision.evidence_refs if ref in visible]
        elif not set(decision.evidence_refs) <= visible:
            raise BehaviorDecisionRejected("behavior evidence is not visible to this NPC")
        if decision.mode_id != state.mode_id and not decision.evidence_refs:
            raise BehaviorDecisionRejected("mode transition requires visible causal evidence")
        if decision.mode_id != state.mode_id and decision.reason_code == "continue":
            # The selected registered mode and validated causal refs are authoritative
            # proposal fields; normalize this redundant label, never invent evidence.
            decision.reason_code = "context_changed"
        if decision.reason_code == "goal_completed":
            verified = {
                x["content_id"]
                for x in source.actor_context.get("known_claims", [])
                if x.get("epistemic_status") in {"observed", "verified"}
            }
            if not any(
                g.status == "completed"
                and g.completion_basis == "observed_event"
                and set(g.evidence_refs) & verified
                and (not state.goal_id or g.id == state.goal_id)
                for g in analysis.goals
            ):
                raise BehaviorDecisionRejected("task exit requires observed goal completion")
        state = state.model_copy(
            update={
                "mode_id": decision.mode_id,
                "reason": decision.reason,
                "evidence_refs": decision.evidence_refs,
                "goal_id": decision.goal_id
                if decision.reason_code != "continue"
                else state.goal_id,
            }
        )
    # Usage hints grant no authority. Reject invalid hints for reinforcement,
    # without replacing an otherwise safe reply with a generic fallback.
    recalled_ids = {m["memory_id"] for m in cognition["recalled_memories"]}
    ignored = sum(ref not in recalled_ids for ref in analysis.used_memory_refs)
    analysis.used_memory_refs = [ref for ref in analysis.used_memory_refs if ref in recalled_ids]
    allowed = set(modes[state.mode_id]["allowed_operations"])
    if any(op.kind not in allowed for op in analysis.operations):
        raise ValueError("operation exceeds configured behavior scope")
    if analysis.collaboration_requests and "consult_npc" not in allowed:
        raise ValueError("collaboration exceeds configured behavior scope")
    return source.model_copy(
        update={
            "actor_context": {
                **source.actor_context,
                "cognition": {
                    **cognition,
                    "effective_behavior": state.model_dump(),
                    "ignored_memory_ref_count": cognition.get("ignored_memory_ref_count", 0)
                    + ignored,
                },
            }
        }
    )
