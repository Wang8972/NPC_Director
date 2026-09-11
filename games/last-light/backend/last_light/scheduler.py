"""Deterministic parallel work scheduler; dialogue never completes these steps."""
from __future__ import annotations

from copy import deepcopy

from .content import ACTIONS, ADULTS


class PlanRules:
    def _plan(self, plan_id):
        return next((p for p in self.state["plans"] if p["id"] == plan_id), None)

    @staticmethod
    def _participants(step):
        return {step["actor_id"], *step["helpers"]}

    def _reservation_keys(self, step):
        return {"actor:" + actor for actor in self._participants(step)} | {
            "resource:" + str(resource) for resource in self._action_resources(step)
        }

    def _plan_conditions(self, plan):
        conditions = []
        for step in plan["steps"]:
            if step["status"] in {"completed", "cancelled", "failed"}:
                continue
            reason = self._check_action(step)
            if reason:
                conditions.append(ACTIONS[step["action_id"]]["label"] + "：" + reason)
        plan["conditions"] = list(dict.fromkeys(conditions))

    def _estimate_plan_ticks(self, steps):
        """List-schedule known dependencies and exclusive resources, not a sum."""
        finishes, available = {}, {}
        remaining = list(steps)
        while remaining:
            ready = next((s for s in remaining if all(d in finishes for d in s["depends_on"])), None)
            if ready is None:
                raise ValueError("任务依赖存在循环。")
            keys = self._reservation_keys(ready)
            start = max([0, *(finishes[d] for d in ready["depends_on"]),
                         *(available.get(key, 0) for key in keys)])
            finishes[ready["id"]] = start + ready["remaining"]
            for key in keys:
                available[key] = finishes[ready["id"]]
            remaining.remove(ready)
        return max(finishes.values(), default=0)

    def propose(self, steps, title=""):
        if self.state["ending"]:
            return self._result(False, "救援已经结束。")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 24:
            return self._result(False, "计划需要1至24项任务。")
        normalized = []
        for index, raw in enumerate(steps):
            if not isinstance(raw, dict):
                return self._result(False, "计划步骤格式不正确。")
            action_id = raw.get("action_id")
            if not isinstance(action_id, str):
                return self._result(False, "任务ID格式不正确。")
            action = ACTIONS.get(action_id)
            actor = raw.get("actor_id")
            if action is None or actor not in action["actors"]:
                return self._result(False, "任务或执行人的能力不匹配。")
            if raw.get("target_id") not in (None, "", action["target_id"]):
                return self._result(False, "任务目标与动作不匹配。")
            helpers, dependencies = raw.get("helpers", []), raw.get("depends_on", [])
            if not isinstance(helpers, list) or any(h not in ADULTS or h == actor for h in helpers):
                return self._result(False, "助手必须是其他可参与工作的成人。")
            if len(helpers) != len(set(helpers)):
                return self._result(False, "助手不能重复。")
            if not isinstance(dependencies, list) or any(not isinstance(d, str) for d in dependencies):
                return self._result(False, "任务依赖必须使用步骤ID。")
            step_id = raw.get("id") or "step_" + str(index + 1)
            if not isinstance(step_id, str) or not 1 <= len(step_id) <= 80:
                return self._result(False, "步骤ID无效。")
            normalized.append({"id": step_id, "action_id": raw["action_id"],
                "actor_id": actor, "target_id": action["target_id"], "helpers": list(helpers),
                "depends_on": list(dict.fromkeys(dependencies)), "duration": action["duration"],
                "remaining": action["duration"], "status": "pending", "reason": ""})
        ids = {s["id"] for s in normalized}
        if len(ids) != len(normalized) or any(set(s["depends_on"]) - ids for s in normalized):
            return self._result(False, "步骤ID重复或引用了不存在的依赖。")
        try:
            estimate = self._estimate_plan_ticks(normalized)
        except ValueError as error:
            return self._result(False, str(error))
        plan = {"id": self._id("plan"), "title": str(title or "救援协作计划")[:120],
                "status": "proposed", "summary": f"{len(normalized)}项任务；确认后按依赖和资源执行。",
                "total_ticks": estimate, "conditions": [], "steps": normalized}
        self._plan_conditions(plan)
        self.state["plans"].append(plan)
        self._changed()
        return self._result(plan_id=plan["id"])

    def begin(self, plan_id):
        if self.state["ending"]:
            return self._result(False, "救援已经结束。")
        if self.state["execution"] is not None:
            return self._result(False, "已有工作正在执行，请先确认执行结果。")
        plan = self._plan(plan_id)
        if plan is None:
            return self._result(False, "找不到这份计划。")
        if plan["status"] in {"completed", "cancelled", "failed"}:
            return self._result(False, "这份计划已经结束。")
        by_id = {step["id"]: step for step in plan["steps"]}
        selected, reserved = [], set()
        for step in plan["steps"]:
            if step["status"] in {"completed", "failed", "cancelled"}:
                continue
            if step["remaining"] <= 0:
                step.update(status="failed", reason="待执行任务的剩余工作量无效。")
                continue
            dependencies = [by_id[d] for d in step["depends_on"]]
            if any(d["status"] in {"failed", "cancelled"} for d in dependencies):
                step.update(status="failed", reason="前置任务未能完成。")
                continue
            if not all(d["status"] == "completed" for d in dependencies):
                step.update(status="waiting", reason="等待前置任务实际完成。")
                continue
            reason = self._check_action(step)
            if reason:
                step.update(status="waiting", reason=reason)
                continue
            keys = self._reservation_keys(step)
            if selected and (ACTIONS[step["action_id"]]["kind"] == "decision" or
                    any(ACTIONS[s["action_id"]]["kind"] == "decision" for s in selected)):
                step.update(status="waiting", reason="结束救援的确认需要单独执行。")
                continue
            if reserved & keys:
                step.update(status="waiting", reason="执行人、助手或资源正用于同批其他工作。")
                continue
            selected.append(step)
            reserved |= keys
        if not selected:
            plan["status"] = "failed" if all(s["status"] in {"completed", "failed", "cancelled"} for s in plan["steps"]) else "waiting"
            self._plan_conditions(plan)
            self._changed()
            return self._result(False, "当前没有满足条件的任务；请查看计划中的待确认事项。")
        for step in selected:
            step.update(status="executing", reason="")
            for actor_id in self._participants(step):
                self.state["actors"][actor_id].update(pose="working", task_status="执行中：" + ACTIONS[step["action_id"]]["label"])
        first = selected[0]
        room = self._target_room(first["target_id"])
        execution = {"id": self._id("execution"), "plan_id": plan_id,
            "step_ids": [s["id"] for s in selected], "steps": deepcopy(selected),
            "actor_ids": sorted({a for s in selected for a in self._participants(s)}),
            "action_id": first["action_id"], "target_id": first["target_id"], "room_id": room,
            "duration": min(s["remaining"] for s in selected)}
        self.state["execution"] = execution
        plan["status"] = "executing"
        self._event("plan_started", f"开始执行「{plan['title']}」的{len(selected)}项并行工作。", execution["actor_ids"])
        self._changed()
        return self._result(execution_id=execution["id"])

    def _release_execution(self, execution):
        for actor_id in execution["actor_ids"]:
            actor = self.state["actors"][actor_id]
            if actor.get("task_status", "").startswith("执行中："):
                actor["task_status"] = ""
            if actor.get("pose") == "working":
                actor["pose"] = "idle"
        self.state["execution"] = None

    def complete(self, execution_id):
        # A batch is one authoritative commit. If an action callback fails after
        # another action changed custody/knowledge, restore the entire batch so
        # replay cannot encounter half-delivered items or a false receipt.
        before = deepcopy(self.state)
        try:
            return self._complete_execution(execution_id)
        except BaseException:
            self.state.clear()
            self.state.update(before)
            raise

    def _complete_execution(self, execution_id):
        if execution_id in self.state["completed_executions"]:
            return self._result()  # retrying a lost HTTP response never costs time
        if execution_id in self.state["cancelled_executions"]:
            return self._result(False, "该批执行已取消，不能再次完成。")
        execution = self.state["execution"]
        if execution is None or execution["id"] != execution_id:
            return self._result(False, "执行ID无效或已经过期。")
        plan = self._plan(execution["plan_id"])
        selected = [s for s in plan["steps"] if s["id"] in execution["step_ids"]]
        paused = False
        elapsed = 0
        for _ in range(execution["duration"]):
            running = []
            for step in selected:
                if step["status"] != "executing":
                    continue
                reason = self._check_action(step)
                if reason:
                    step.update(status="waiting", reason=reason)
                else:
                    running.append(step)
            if not running:
                break
            # Every parallel participant works during the SAME world tick.
            for step in running:
                step["remaining"] -= 1
            for step in running:
                if step["remaining"] != 0:
                    continue
                # An earlier completion in this batch may have changed custody,
                # consent or another precondition. Recheck immediately at commit.
                reason = self._check_action(step)
                if reason:
                    step.update(status="waiting", remaining=1, reason=reason)
                    continue
                self._apply_action(step)
                step.update(status="completed", reason="")
            elapsed += 1
            paused = bool(self._advance_time(1))
            if paused or self.state["ending"]:
                break
        for step in selected:
            if step["status"] == "executing":
                step.update(status="waiting" if paused else "pending",
                            reason="现场条件变化，请重新确认后续安排。" if paused else "")
        self._release_execution(execution)
        self.state["completed_executions"].append(execution_id)
        if all(s["status"] == "completed" for s in plan["steps"]):
            plan["status"] = "completed"
            self._event("plan_completed", f"「{plan['title']}」的任务均已实际完成。", execution["actor_ids"])
        elif self.state["ending"]:
            plan["status"] = "failed"
            for step in plan["steps"]:
                if step["status"] not in {"completed", "cancelled"}:
                    step.update(status="cancelled", reason="本次救援已结束，任务未执行。")
        else:
            plan["status"] = "waiting" if paused or any(s["reason"] for s in plan["steps"] if s["status"] != "completed") else "accepted"
        self._plan_conditions(plan)
        if paused:
            self._event("plan_paused", "出现新的现场条件，已完成的工作保留，后续安排等待重新确认。", execution["actor_ids"])
        self._changed()
        return self._result(elapsed_ticks=elapsed, paused=paused)

    def cancel(self, plan_id):
        plan = self._plan(plan_id)
        if plan is None:
            return self._result(False, "找不到这份计划。")
        if plan["status"] in {"cancelled", "completed"}:
            return self._result()
        execution = self.state["execution"]
        if execution is not None and execution["plan_id"] == plan_id:
            self.state["cancelled_executions"].append(execution["id"])
            self._release_execution(execution)
        for step in plan["steps"]:
            if step["status"] != "completed":
                step.update(status="cancelled", reason="计划已撤回；此前实际结果不会回滚。")
        plan["status"] = "cancelled"
        plan["conditions"] = []
        self._event("plan_cancelled", f"「{plan['title']}」未完成的工作已取消，物品和人员保留实际状态。", ["player"])
        self._changed()
        return self._result()
