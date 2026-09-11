"""Delivered social agreements, deliberately separate from physical execution."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from .content import ACTIONS, ACTOR_IDS, ADULTS, FACTS, NAMES, NPC_IDS


SUPPORTED_CONDITIONS = frozenset({
    "isolation_verified", "traffic_confirmed", "path_surveyed", "child_reunited",
    "mother_protected", "valid_loan", "with_helper", "preserve_evidence",
    "retest_before_restore",
})
HELPER_KINDS = frozenset({"carry", "repair", "rescue", "care", "protect", "inspect"})


class SocialRules:
    def _can_accept_task(self, npc_id, action_id, role="actor"):
        spec = ACTIONS.get(action_id)
        return bool(spec and ((role == "actor" and npc_id in spec["actors"])
                              or (role == "helper" and spec["kind"] in HELPER_KINDS)))

    def _social_audience(self, speaker, requested=None, channel="local"):
        if channel not in {"local", "radio"}:
            raise ValueError("未支持的消息传递渠道。")
        if requested is None:
            requested = self._actors_at(self.state["actors"][speaker]["room_id"])
        if not isinstance(requested, list) or any(a not in ACTOR_IDS for a in requested):
            raise ValueError("消息受众无效。")
        audience = list(dict.fromkeys(requested))
        powered = self.has("aux_restored") or (
            self.state["items"]["backup"]["connected_to"] == "radio"
            and self.state["items"]["backup"]["charge"] > 0
        )
        for actor in audience:
            same_room = self.state["actors"][actor]["room_id"] == self.state["actors"][speaker]["room_id"]
            if not same_room and not (channel == "radio" and powered):
                raise ValueError("对方不在实际可听范围，不能凭空送达消息。")
        return audience

    def apply_decision(self, npc_id, decision):
        if npc_id not in NPC_IDS or not isinstance(decision, dict):
            return self._result(False, "社会决定需要有效的NPC与结构化内容。")
        kind = decision.get("kind")
        handlers = {"share_fact": self._share_fact, "accept_task": self._accept_task,
                    "loan": self._accept_loan, "child_delegation": self._delegate_child,
                    "withdraw_loan": self._withdraw_loan, "revoke_task": self._revoke_task}
        if not isinstance(kind, str) or kind not in handlers:
            return self._result(False, "未支持的社会决定；台词不能写入物理状态。")
        decision_id = decision.get("decision_id")
        if decision_id is not None and (not isinstance(decision_id, str) or not 1 <= len(decision_id) <= 180):
            return self._result(False, "决定ID格式不正确。")
        material = {k: v for k, v in decision.items() if k not in {"decision_id", "basis_revision"}}
        digest = hashlib.sha256(json.dumps([npc_id, material], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if decision_id:
            old = next((r for r in self.state["applied_decisions"] if isinstance(r, dict) and r.get("id") == decision_id), None)
            if old:
                if old["digest"] != digest:
                    return self._result(False, "同一决定ID不能复用于不同内容。")
                return self._result(old["ok"], old["error"])
        try:
            handlers[kind](npc_id, decision)
            ok, error = True, ""
        except ValueError as invalid:
            ok, error = False, str(invalid)
        self.state["applied_decisions"].append({"id": decision_id or self._id("decision"),
            "digest": digest, "ok": ok, "error": error, "tick": self.state["tick"],
            "basis_revision": decision.get("basis_revision")})
        self._changed()
        return self._result(ok, error)

    @staticmethod
    def _id_list(decision, key, catalog):
        values = decision.get(key, [])
        if not isinstance(values, list) or not 1 <= len(values) <= max(24, len(catalog)) or any(not isinstance(v, str) or v not in catalog for v in values):
            raise ValueError("决定包含未知的" + key + "。")
        return list(dict.fromkeys(values))

    def _share_fact(self, npc_id, decision):
        source = decision.get("source_actor_id", npc_id)
        if source not in {npc_id, "player"}:
            raise ValueError("不能代替未发言角色提供其私有知识。")
        facts = self._id_list(decision, "fact_ids", FACTS)
        if any(not self.knows(source, fact_id) for fact_id in facts):
            raise ValueError("说话者并不持有这条事实的真实来源。")
        requested = decision.get("audience", [npc_id] if source == "player" else None)
        audience = self._social_audience(source, requested, decision.get("channel", "local"))
        if not audience:
            raise ValueError("消息需要明确的实际接收人。")
        for fact_id in facts:
            original = next(f for f in self.state["knowledge"][source] if f["id"] == fact_id)
            quality = original["quality"] if source == "player" else "reported"
            self._learn(fact_id, audience, source=NAMES[source] + ("出示材料" if source == "player" else "告知"), quality=quality)
        event = self._event("fact_shared", NAMES[source] + "向在场接收人说明了有来源的信息。",
                            [source, *audience], actor_ids=[source])
        # _event's fact_ids parameter promotes witnessed physical results. A
        # spoken report must not go through that verified-world-event path.
        event["fact_ids"] = facts
        if source == npc_id and set(facts) & {"crew_report", "radio_lost", "temporary_fix"}:
            self.state["social"][npc_id]["disclosure"] = "shared"
        delegation = self.state["social"]["zhou"].get("child_delegation")
        if delegation and "zhou" in audience and set(facts) & {"child_checked", "child_reunited"}:
            if delegation.get("status") in {"active", "needs_update"}:
                delegation.update(status="fulfilled", reported_tick=self.state["tick"],
                                  report_late=self.state["tick"] > delegation["checkpoint_tick"])
                for promise in self.state["promises"]:
                    if promise.get("id") == delegation["id"]:
                        promise.update(delegation)

    def _accept_task(self, npc_id, decision):
        actions = self._id_list(decision, "action_ids", ACTIONS)
        role = decision.get("role", "actor")
        if role not in {"actor", "helper"} or any(not self._can_accept_task(npc_id, aid, role) for aid in actions):
            raise ValueError("角色不能接受自己无能力执行或协助的工作。")
        conditions = decision.get("conditions", [])
        if not isinstance(conditions, list) or any(not isinstance(c, str) or c not in SUPPORTED_CONDITIONS for c in conditions):
            raise ValueError("合作条件必须使用受支持的规则标签。")
        conditions = list(dict.fromkeys(conditions))
        for aid in actions:
            accepted = self.state["social"][npc_id]["accepted_tasks"]
            if aid not in accepted:
                accepted.append(aid)
            for old in self.state["promises"]:
                if old.get("kind") == "task" and old.get("npc_id") == npc_id and old.get("action_id") == aid and old.get("status") == "accepted":
                    old.update(status="superseded", superseded_tick=self.state["tick"])
            self.state["promises"].append({"id": self._id("promise"), "kind": "task",
                "npc_id": npc_id, "action_id": aid, "conditions": conditions,
                "role": role,
                "status": "accepted", "tick": self.state["tick"],
                "witnesses": self._actors_at(self.state["actors"][npc_id]["room_id"])})
        self._event("task_accepted", NAMES[npc_id] + "接受了分工；工作尚未执行。",
                    self._actors_at(self.state["actors"][npc_id]["room_id"]), actor_ids=[npc_id])

    def _social_condition_reason(self, npc_id, step):
        promise = next((p for p in reversed(self.state["promises"]) if p.get("kind") == "task"
            and p.get("npc_id") == npc_id and p.get("action_id") == step["action_id"]
            and p.get("status") == "accepted"), None)
        if promise and promise.get("role") == "helper" and step["actor_id"] == npc_id:
            return NAMES[npc_id] + "只同意协助，需要另一个具备能力的主执行人。"
        for condition in promise.get("conditions", []) if promise else []:
            if condition in {"isolation_verified", "traffic_confirmed", "path_surveyed", "child_reunited"}:
                if not self.has(condition):
                    return NAMES[npc_id] + "要求先实际满足条件：" + condition
            elif condition == "mother_protected":
                room = self.state["actors"]["mother"]["room_id"]
                if room not in {"cabin07", "tunnel"} or self._smoke(room):
                    return "先把许母转移到没有烟气的照护位置。"
            elif condition == "valid_loan":
                reason = self._loan_invalid_reason(self._loan())
                if reason:
                    return reason
            elif condition == "with_helper":
                if not step.get("helpers"):
                    return NAMES[npc_id] + "要求另一名实际参加的成人协助。"
            elif condition not in {"preserve_evidence", "retest_before_restore"}:
                return "合作约定含不受支持的条件。"
        return ""

    def _accept_loan(self, npc_id, decision):
        if npc_id != "xu" or decision.get("purpose") != "radio":
            raise ValueError("只有许宁能同意这份限定用途的备用电源借约。")
        recipient = decision.get("recipient_id")
        deadline, reserve = decision.get("deadline_tick"), decision.get("reserve")
        if recipient not in {"player", "lin", "chen"}:
            raise ValueError("借电约定需要具备通信任务能力的明确接收人。")
        if type(deadline) is not int or not self.state["tick"] < deadline <= self.state["tick"] + 100:
            raise ValueError("归还节点必须是未来的明确行动时间。")
        if type(reserve) is not int or not 1 <= reserve <= 100:
            raise ValueError("保留电量必须是正整数。")
        loan = {"kind": "loan", "npc_id": "xu", "purpose": "radio", "recipient_id": recipient,
                "deadline_tick": deadline, "reserve": reserve, "status": "accepted", "tick": self.state["tick"]}
        reason = self._loan_invalid_reason(loan, taking=True)
        if reason:
            raise ValueError(reason)
        old = self._loan()
        if old and old.get("status") not in {"returned", "superseded"}:
            old.update(status="superseded", superseded_tick=self.state["tick"])
        loan["id"] = self._id("promise")
        loan["witnesses"] = self._actors_at(self.state["actors"]["xu"]["room_id"])
        self.state["promises"].append(loan)
        self._event("loan_accepted", "许宁同意了有用途、期限与保留电量的借约；电源仍在实际位置。",
                    loan["witnesses"], actor_ids=["xu", recipient], target_id="backup_supply")

    def _delegate_child(self, npc_id, decision):
        if npc_id != "zhou" or self.has("child_reunited"):
            raise ValueError("当前不能建立新的寻人委托。")
        rescuer, checkpoint = decision.get("rescuer_id"), decision.get("checkpoint_tick")
        if rescuer not in ADULTS or rescuer == "zhou":
            raise ValueError("需要另一名实际接受工作的救援者。")
        if type(checkpoint) is not int or not self.state["tick"] < checkpoint <= self.state["tick"] + 100:
            raise ValueError("委托必须有未来的明确回报节点。")
        selected = None
        for plan in self.state["plans"]:
            # World plans exist only after the player confirms/proposes them;
            # raw AI suggested_steps never enter this store. Requiring begin()
            # here would make delegation impossible before an execution starts.
            if plan["status"] not in {"proposed", "accepted", "waiting", "executing"}:
                continue
            for step in plan["steps"]:
                if step["actor_id"] != rescuer or step["action_id"] not in {"check_child", "reunite_child"}:
                    continue
                if step["status"] in {"completed", "cancelled", "failed"}:
                    continue
                accepted = rescuer == "player" or step["action_id"] in self.state["social"][rescuer]["accepted_tasks"]
                if accepted and not self._check_action(step) and checkpoint >= self.state["tick"] + step["remaining"]:
                    selected = (plan, step)
                    break
            if selected:
                break
        if selected is None:
            raise ValueError("尚无该救援者已接受且可执行的寻人任务，不能用空口保证替代。")
        plan, step = selected
        delegation = {"id": self._id("promise"), "kind": "child_delegation", "npc_id": "zhou",
            "rescuer_id": rescuer, "checkpoint_tick": checkpoint, "status": "active",
            "plan_id": plan["id"], "step_id": step["id"], "action_id": step["action_id"],
            "tick": self.state["tick"], "actor_ids": ["zhou", rescuer],
            "witnesses": self._actors_at(self.state["actors"]["zhou"]["room_id"])}
        old = self.state["social"]["zhou"].get("child_delegation")
        if old and old.get("status") in {"active", "needs_update"}:
            old["status"] = "superseded"
            for promise in self.state["promises"]:
                if promise.get("id") == old.get("id"):
                    promise["status"] = "superseded"
        self.state["social"]["zhou"]["child_delegation"] = deepcopy(delegation)
        self.state["promises"].append(delegation)
        self._event("child_delegation_accepted", "周屿确认了实际救援者、已有任务和回报节点。",
                    delegation["witnesses"], actor_ids=["zhou", rescuer], target_id="child")

    def _withdraw_loan(self, npc_id, decision):
        loan = self._loan()
        if npc_id != "xu" or not loan or loan.get("status") not in {"accepted", "active", "reclaim_requested"}:
            raise ValueError("当前没有许宁可以撤回或重谈的借约。")
        reason = loan.get("reclaim_reason", "") if loan["status"] == "reclaim_requested" else self._loan_invalid_reason(loan)
        if not reason:
            raise ValueError("借约保障条件未改变，不能凭空把许宁写成反悔。")
        loan.update(status="reclaim_requested", reclaim_reason=reason, reclaim_tick=self.state["tick"])
        self._event("loan_reclaim_requested", "借约条件已经改变，许宁要求重谈或实际归还电源。",
                    self._actors_at(self.state["actors"]["xu"]["room_id"]), actor_ids=["xu"], target_id="backup_supply")

    def _revoke_task(self, npc_id, decision):
        actions = self._id_list(decision, "action_ids", ACTIONS)
        accepted = self.state["social"][npc_id]["accepted_tasks"]
        if any(aid not in accepted for aid in actions):
            raise ValueError("只能撤回自己已接受的工作。")
        reason = str(decision.get("reason", "重新考虑当前安排"))[:400]
        self.state["social"][npc_id]["accepted_tasks"] = [aid for aid in accepted if aid not in actions]
        for promise in self.state["promises"]:
            if promise.get("kind") == "task" and promise.get("npc_id") == npc_id and promise.get("action_id") in actions and promise.get("status") == "accepted":
                promise.update(status="revoked", revoked_tick=self.state["tick"], reason=reason)
        self.state["social"][npc_id]["refusals"].append({"action_ids": actions, "reason": reason, "tick": self.state["tick"]})
        # Existing execution is deliberately untouched. Its next safe boundary
        # rechecks consent; prior physical results, custody and charge stay real.
        self._event("task_consent_revoked", NAMES[npc_id] + "撤回了尚未完成的合作安排。",
                    self._actors_at(self.state["actors"][npc_id]["room_id"]), actor_ids=[npc_id])

    def record_dialogue(self, npc_id, text, line_id, source="live", emotion="", audience=None):
        if npc_id not in (*NPC_IDS, "player") or not isinstance(text, str) or not text.strip() or len(text) > 8000:
            return self._result(False, "发言角色或文本无效。")
        if not isinstance(line_id, str) or not 1 <= len(line_id) <= 180:
            return self._result(False, "发言ID无效。")
        if source not in {"live", "rehearsal", "recorded", "narrative"}:
            return self._result(False, "发言来源无效。")
        previous = next((r for r in self.state["delivered_lines"] if isinstance(r, dict) and r.get("id") == line_id), None)
        if previous:
            same = previous["npc_id"] == npc_id and previous["text"] == text and previous["source"] == source
            return self._result(same, "" if same else "同一发言ID不能替换已经送达的内容。")
        try:
            heard = self._social_audience(npc_id, audience)
        except ValueError as invalid:
            return self._result(False, str(invalid))
        line = {"id": line_id, "npc_id": npc_id, "text": text, "source": source,
                "emotion": str(emotion)[:40], "audience": heard, "tick": self.state["tick"]}
        self.state["delivered_lines"].append(line)
        if "player" in heard:
            self._say(npc_id, text, source=source, emotion=str(emotion)[:40], line_id=line_id)
        self._event("dialogue_delivered", text, [npc_id, *heard], actor_ids=[npc_id])
        self._changed()
        return self._result()
