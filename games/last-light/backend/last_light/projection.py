"""Read-only, audience-specific JSON views for Unity and NPC Director."""
from copy import deepcopy

from .content import ACTIONS, ACTOR_IDS, FACTS, NAMES, NPC_IDS, NPCS, OBJECTS, ROOMS, TOPICS
from .social_rules import SUPPORTED_CONDITIONS
from .presentation_content import presentation_for


class Projection:
    def _visible_entity_ids(self, viewer="player"):
        room = self.state["actors"][viewer]["room_id"]
        entities = set(self._actors_at(room))
        entities.update(oid for oid in OBJECTS if self._target_room(oid) == room)
        entities.update(item["id"] for item in self._visible_inventory(viewer) if item["state"] != "consumed")
        if room == "tunnel":
            entities.add("outer_door05")
        return entities

    def _actor_presentation(self, aid, viewer="player"):
        room = self.state["actors"][viewer]["room_id"]
        if self.state["actors"][aid]["room_id"] != room:
            return {"activity": "unobserved", "attention_target_id": "", "health_display": "unknown", "companions": []}
        visible = self._visible_entity_ids(viewer)
        activity, attention, health, companions = "idle", "", "unassessed", []
        mother_carer = self.state.get("mother_caregiver", "xu")
        child_carer = self.state.get("child_caregiver", "passenger05")
        child_relation_known = any(self.knows(viewer, fid) for fid in ("child_last_seen", "child_checked", "child_reunited"))
        for subject, carer in (("mother", mother_carer), ("xiaoman", child_carer)):
            if subject not in visible or carer not in visible or (subject == "xiaoman" and not child_relation_known):
                continue
            if aid == carer:
                companions.append(subject)
                activity, attention = "caregiving", subject
            elif aid == subject:
                companions.append(carer)
                attention = carer
        if aid == "mother":
            activity = "resting"
            # Visible breathing/posture, not an unseen diagnosis or predicted outcome.
            health = "needs_support" if self.state["hazard"]["mother_worse"] else "using_device"
            if self.state["hazard"]["mother_injured"]:
                health = "needs_urgent_support"
        elif aid == "xiaoman":
            activity = "resting"
            checked = next((f for f in self.state["knowledge"][viewer] if f["id"] == "child_checked"), None)
            if checked:
                health = "reported_minor_scratches" if checked["quality"] == "reported" else "minor_scratches"
        elif not attention:
            defaults = {"lin": ("checking_radio", "radio"), "chen": ("checking_equipment", "cabinet"),
                        "zhou": ("waiting_at_door", "blocked_door" if "blocked_door" in visible else "outer_door07"),
                        "xu": ("caregiving", "mother")}
            if aid in defaults:
                candidate, target = defaults[aid]
                if target in visible:
                    activity, attention = candidate, target
        execution = self.state["execution"]
        if execution:
            plan = next((p for p in self.state["plans"] if p["id"] == execution["plan_id"]), None)
            for work in (plan or {}).get("steps", []):
                if work["id"] in execution.get("step_ids", []) and aid in [work["actor_id"], *work.get("helpers", [])]:
                    activity = "working"
                    attention = work["target_id"] if work["target_id"] in visible else ""
                    break
        return {"activity": activity, "attention_target_id": attention if attention in visible else "",
                "health_display": health, "companions": list(dict.fromkeys(companions))}

    def _actor_view(self, aid, viewer="player"):
        actor = self.state["actors"][aid]
        role = NPCS.get(aid, {}).get("role", {"player": "普通乘客", "mother": "许母", "xiaoman": "小乘客"}.get(aid, "乘客"))
        if aid == "zhou" and self.knows(viewer, "child_last_seen"):
            role = "小满的父亲"
        return {"id": aid, "name": NAMES[aid], "role": role, "room_id": actor["room_id"],
                "pose": actor.get("pose", "idle"), "emotion": actor.get("emotion", "neutral"),
                "carrying": actor.get("carrying", ""), "task_status": actor.get("task_status", ""),
                "x": actor["x"], "z": actor["z"], **self._actor_presentation(aid, viewer)}

    def _object_state(self, oid):
        if oid == "blocked_door":
            return "open" if self.has("inner_door_open") else "cleared" if self.has("trolley_cleared") else "jammed"
        if oid == "outer_door07":
            return "open" if self.has("outer_open") else "closed"
        if oid == "outer_door05":
            return "open" if self.has("external05_open") else "closed"
        if oid == "cabinet":
            return "isolated" if self.has("aux_isolated") else "live"
        if oid == "cable_joint":
            for flag, label in (("aux_restored", "powered"), ("retest_passed", "tested"), ("repair_done", "repaired")):
                if self.has(flag):
                    return label
            if self.has("joint_diagnosed"):
                return "isolated_diagnosed" if self.has("aux_isolated") else "diagnosed"
            return "unexamined"
        if oid == "power_bus":
            for flag, label in (("aux_restored", "powered"), ("retest_passed", "tested"), ("repair_done", "repaired"), ("aux_isolated", "isolated")):
                if self.has(flag):
                    return label
            return "unexamined"
        if oid == "vent06":
            return "closed" if self.has("vent_closed") else "open"
        if oid == "aisle07":
            return "clear" if self.has("aisle_clear") else "cluttered"
        if oid == "tool_rack":
            stored = [iid for iid in ("tools", "lamp", "spares") if not self.state["items"][iid]["holder_id"] and self.state["items"][iid]["state"] == "stored"]
            return ",".join(stored) or "empty"
        if oid == "stretcher_rack":
            item = self.state["items"]["stretcher"]
            return "stored" if not item["holder_id"] and item["state"] == "stored" else "empty"
        if oid == "fixed_phone":
            return "ready" if self.has("phone_restored") else "needs_interface"
        if oid == "oxygen":
            medical, backup = self.state["items"]["medical"], self.state["items"]["backup"]
            if medical["connected_to"] == "backup" and backup["connected_to"] == "medical" and backup["charge"] > 0:
                return "running_backup"
            if medical["connected_to"] == "internal" and medical["charge"] > 0:
                return "running_internal"
            return "unpowered"
        if oid == "backup_supply":
            item = self.state["items"]["backup"]
            if item["charge"] <= 0:
                return "depleted"
            return {"radio": "connected_radio", "medical": "connected_medical"}.get(item["connected_to"], "held")
        if oid == "radio":
            backup = self.state["items"]["backup"]
            return "powered" if self.has("aux_restored") or (backup["connected_to"] == "radio" and backup["charge"] > 0) else "unpowered"
        if oid == "walkway":
            return "lit" if self.has("route_lit") else "dark"
        return "observed" if oid in self.state["inspected"] else "available"

    def _object_position(self, oid):
        spec = OBJECTS[oid]
        x, z = spec["x"], spec["z"]
        if oid == "oxygen":
            person = self.state["actors"]["mother"]
            x, z = person["x"] + .6, person["z"] - .4
        elif oid == "backup_supply":
            item = self.state["items"]["backup"]
            if item["connected_to"] == "radio":
                x, z = OBJECTS["radio"]["x"] + .7, OBJECTS["radio"]["z"] - .15
            elif item["connected_to"] == "medical":
                person = self.state["actors"]["mother"]
                x, z = person["x"] + .7, person["z"] - .2
            elif item["holder_id"] in self.state["actors"]:
                person = self.state["actors"][item["holder_id"]]
                x, z = person["x"] + .45, person["z"] + .25
        return min(7.5, max(-7.5, x)), min(2, max(-2, z))

    def _objects_in(self, room_id):
        result = []
        for oid, spec in OBJECTS.items():
            if self._target_room(oid) != room_id:
                continue
            x, z = self._object_position(oid)
            result.append({"id": oid, "label": spec["label"], "room_id": room_id,
                           "x": x, "z": z, "state": self._object_state(oid),
                           "description": spec["description"], "interactable": not bool(self.state["ending"])})
        if room_id == "tunnel":
            result.append({"id": "outer_door05", "label": "05号外门·外侧释放口", "room_id": "tunnel",
                           "x": -6, "z": 1.6, "state": self._object_state("outer_door05"),
                           "description": "沿已核实步道能抵达外侧释放口；此处看不到05号车厢内部。",
                           "interactable": not bool(self.state["ending"])})
        return result

    def _action_visible(self, action_id, viewer):
        spec = ACTIONS[action_id]
        room = "tunnel" if action_id == "open_external05" else self._target_room(spec["target_id"])
        if viewer == "player":
            known_room = room in self.state["visited"]
        else:
            known_room = room == self.state["actors"][viewer]["room_id"]
            known_room |= room in ("cabin06", "cabin07", "service") and self.knows(viewer, "inner_route_open")
        child_known = any(self.knows(viewer, f) for f in ("child_last_seen", "child_audible", "child_checked"))
        if spec["target_id"] == "child" and not child_known and self.state["actors"][viewer]["room_id"] != "cabin05":
            return False
        if spec["target_id"] == "child" and child_known:
            known_room = True
        if room == "tunnel":
            return self.knows(viewer, "path_surveyed") or self.state["actors"][viewer]["room_id"] == "tunnel"
        return known_room

    def _action_view(self, action_id, viewer="player"):
        spec = ACTIONS[action_id]
        default = viewer if viewer in spec["actors"] else spec["actors"][0]
        step = {"id": "preview", "action_id": action_id, "actor_id": default,
                "target_id": spec["target_id"], "helpers": [], "depends_on": [], "remaining": spec["duration"]}
        reason = self._check_action(step)
        if self.state["ending"]:
            reason = "本次救援已经结束。"
        return {"id": action_id, "label": spec["label"], "description": spec["description"],
                "target_id": spec["target_id"], "kind": spec["kind"], "duration": spec["duration"],
                "default_actor": default, "actor_ids": list(spec["actors"]),
                "enabled": not bool(reason), "blocked_reason": reason}

    @property
    def objective(self):
        if self.state["ending"]:
            return "查看救援结果与人物后记，或从检查点重新安排。"
        if self.state["execution"]:
            return "行动已预约。演出完成后提交本批结果；等待演出和阅读都不额外耗时。"
        if not self.knows("player", "child_last_seen") and not self.knows("player", "crew_report"):
            return "观察07号车厢，与林岚和周屿交谈。06与检修间仍可进入；探索和对话不推进危机。"
        if not self.has("aux_isolated"):
            return "先核实热源与照护需求。检修间可隔离辅助支路，06前门可安排两人排障。"
        if not self.has("child_checked"):
            return "热源已控制。打开05内门或核实安全外路，实际联系并检查小满；同时保护许母。"
        if not self.has("rescue_contact"):
            return "用独立固定电话，或协商借电接通无线设备，取得调度回执。"
        if self.has("route_lit") and not self.has("final_sweep"):
            return "沿已核实路线分别转移孩子、许母与其他乘客；完成最后人员和设备清点。"
        if self.has("aux_restored") and self.has("group_sheltered"):
            return "确认孩子和许母都已到场，完成清点与最后检查，再决定留车接应。"
        return "选择救援安排：完成复测与车内集合后留车接应，或核实外路并分批转移到避险点。"

    @property
    def chapter(self):
        if self.state["ending"]:
            return "尾声 · 留下的光"
        if self.has("route_lit") or self.has("aux_restored"):
            return "第三幕 · 一起走完"
        if self.has("aux_isolated") or self.has("child_audible") or self.has("mother_assessed"):
            return "第二幕 · 承诺的条件"
        return "第一幕 · 停车之后"

    def _item_endpoint(self, item_id):
        item = self.state["items"][item_id]
        connected = {"radio": "radio", "medical": "oxygen", "walkway": "walkway"}
        if item["connected_to"] in connected:
            return connected[item["connected_to"]]
        if item["holder_id"]:
            return item["holder_id"]
        if item["state"] == "stored":
            return "stretcher_rack" if item_id == "stretcher" else "tool_rack"
        return item_id

    def _step_presentation(self, step, viewer="player"):
        """Resolve only currently visible endpoints; never invent an offscreen cast."""
        action_id, actor = step["action_id"], step["actor_id"]
        spec = ACTIONS[action_id]
        presentation = presentation_for(action_id)
        room = self.state["actors"][viewer]["room_id"]
        visible = self._visible_entity_ids(viewer)
        target = step.get("target_id", spec["target_id"])
        source, destination = actor, target
        participants = [actor, *step.get("helpers", [])]
        resources = list(presentation["resource_ids"])
        primary = resources[0] if resources else ""
        if action_id in {"move_mother", "escort_mother"} and self.state["items"]["backup"]["connected_to"] != "medical":
            resources = [iid for iid in resources if iid != "backup"]
        if action_id == "radio_request" and self.state["items"]["backup"]["connected_to"] != "radio":
            resources = []
        if action_id.startswith("collect_"):
            source, destination = self._item_endpoint(primary), actor
        elif action_id in {"give_tools", "give_spares", "give_lamp", "take_backup", "return_backup"}:
            source = self._item_endpoint(primary)
            recipient = {"give_tools": "chen", "give_spares": "chen", "give_lamp": "lin", "take_backup": actor, "return_backup": "xu"}[action_id]
            destination = recipient
            participants.extend([source, recipient])
        elif action_id in {"connect_radio", "connect_medical"}:
            source, destination = self._item_endpoint("backup"), target
            participants.append(source)
        elif action_id in {"disconnect_radio", "disconnect_medical"}:
            source, destination = target, actor
        elif action_id in {"move_mother", "escort_mother"}:
            source, destination = "mother", "aisle07" if action_id == "move_mother" else "refuge"
            participants.append("mother")
        elif action_id in {"reunite_child", "escort_child"}:
            source, destination = "xiaoman", "aisle07" if action_id == "reunite_child" else "refuge"
            participants.append("xiaoman")
        elif action_id == "assign_child_care":
            source, destination = self.state.get("child_caregiver", "passenger05"), actor
            participants.extend([source, "xiaoman"])
        elif action_id in {"shelter_group", "escort_passengers"}:
            candidates = [aid for aid in ("passenger05", "passenger07") if aid in visible]
            source = candidates[0] if candidates else ""
            participants.extend(candidates)
        elif action_id == "prepare_stretcher":
            source = self._item_endpoint("stretcher")
        if "patient" in presentation["participant_roles"]:
            participants.append("mother")
        if "child" in presentation["participant_roles"]:
            participants.append("xiaoman")
        if "passengers" in presentation["participant_roles"]:
            participants.extend(["passenger05", "passenger07"])
        source = source if source in visible else ""
        destination = destination if destination in visible else ""
        item_ids = [iid for iid in resources if iid in visible and self.state["items"][iid]["state"] != "consumed"]
        return {"presentation": presentation, "visible_target_id": target if target in visible else "",
                "source_id": source, "destination_id": destination, "item_ids": item_ids,
                "participant_ids": list(dict.fromkeys(aid for aid in participants if aid in visible and aid in ACTOR_IDS)),
                "source_room_id": room if source else "", "destination_room_id": room if destination else ""}

    def _step_view(self, step, viewer="player"):
        spec = ACTIONS[step["action_id"]]
        return {"id": step["id"], "action_id": step["action_id"], "actor_id": step["actor_id"],
                "target_id": step.get("target_id", spec["target_id"]), "status": step.get("status", "proposed"),
                "reason": step.get("reason", ""), "helpers": list(step.get("helpers", [])),
                "depends_on": list(step.get("depends_on", [])), "duration": spec["duration"],
                "remaining": step.get("remaining", spec["duration"]), **self._step_presentation(step, viewer)}

    def _plan_view(self, plan):
        return {"id": plan["id"], "title": plan.get("title", "救援安排"), "status": plan.get("status", "proposed"),
                "summary": plan.get("summary", "独立任务可并行，实际消耗在每批确认前显示。"),
                "total_ticks": plan.get("total_ticks", sum(ACTIONS[s["action_id"]]["duration"] for s in plan["steps"])),
                "conditions": list(plan.get("conditions", [])), "steps": [self._step_view(s) for s in plan["steps"]]}

    def _execution_view(self):
        execution = self.state["execution"]
        if not execution:
            return None
        plan = next(p for p in self.state["plans"] if p["id"] == execution["plan_id"])
        steps = [s for s in plan["steps"] if s["id"] in execution.get("step_ids", [])]
        if not steps and execution.get("steps"):
            steps = execution["steps"]
        first = steps[0] if steps else {}
        actors = list(dict.fromkeys(a for s in steps for a in [s["actor_id"], *s.get("helpers", [])]))
        return {"id": execution["id"], "plan_id": execution["plan_id"],
                "action_id": first.get("action_id", ""), "target_id": first.get("target_id", ""),
                "room_id": self._action_room(first) if first else "", "actor_ids": actors,
                "duration": execution["duration"], "steps": [self._step_view(s) for s in steps]}

    def _visible_inventory(self, viewer):
        room = self.state["actors"][viewer]["room_id"]
        result = [deepcopy(item) for item in self.state["items"].values()
                  if item["holder_id"] == viewer or item["room_id"] == room]
        for item in result:
            item["visual_state"] = ("unfolded" if self.has("stretcher_prepared") else "folded") if item["id"] == "stretcher" else item["state"]
        return result

    def _direct_neighbors(self, room):
        neighbors = {"cabin07": ["cabin06", "service"], "cabin06": ["cabin07"],
                     "cabin05": [], "service": ["cabin07"], "tunnel": []}
        if self.has("inner_door_open"):
            neighbors["cabin06"].append("cabin05")
            neighbors["cabin05"].append("cabin06")
        if self.has("outer_open"):
            neighbors["cabin07"].append("tunnel")
            neighbors["tunnel"].append("cabin07")
        if self.has("external05_open"):
            neighbors["tunnel"].append("cabin05")
            neighbors["cabin05"].append("tunnel")
        return neighbors[room]

    def _first_exit(self, origin, target):
        queue = [(origin, "")]
        seen = {origin}
        while queue:
            room, first = queue.pop(0)
            if room == target:
                return first
            for neighbor in self._direct_neighbors(room):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append((neighbor, first or neighbor))
        return ""

    def view(self):
        room = self.state["room_id"]
        result = {key: self.state[key] for key in ("session_id", "mode", "revision", "tick", "room_id", "ending", "ending_title", "ending_text")}
        result.update(objective=self.objective, chapter=self.chapter,
                      actors=[self._actor_view(aid) for aid in self._actors_at(room)], objects=self._objects_in(room),
                      inventory=self._visible_inventory("player"), journal=deepcopy(self.state["journal"]),
                      dialogue=[deepcopy(line) for line in self.state["dialogue"] if "_audience" not in line or "player" in line["_audience"]],
                      actions=[self._action_view(aid) for aid in ACTIONS if self._action_visible(aid, "player")],
                      plans=[self._plan_view(p) for p in self.state["plans"]], execution=self._execution_view(),
                      topics=[deepcopy(t) for t in TOPICS if self.state["actors"][t["npc_id"]]["room_id"] == room
                              and (t["id"] != "zhou_help" or self.knows("player", "child_last_seen"))],
                      epilogues=deepcopy(self.state["epilogues"]))
        result["rooms"] = [{"id": rid, "title": spec[0], "description": spec[1] if rid in self.state["visited"] else "尚未进入，内部情况未知。",
                            "accessible": self.can_visit(rid), "direct_accessible": rid in self._direct_neighbors(room), "exit_via": self._first_exit(room, rid) if self.can_visit(rid) else "", "visited": rid in self.state["visited"],
                            "lighting": "unknown" if rid != room else ("lit" if self.has("route_lit") else "dark") if rid == "tunnel" else ("restored" if self.has("aux_restored") else "emergency"),
                            "smoke": self._smoke(rid) if rid == room else 0} for rid, spec in ROOMS.items()]
        return result

    def _fact_views(self, actor_id):
        return [{"id": record["id"], "text": FACTS[record["id"]][1], "title": FACTS[record["id"]][0],
                 "source": record["source"], "quality": record["quality"], "tick": record["tick"]}
                for record in self.state["knowledge"][actor_id]]

    def npc_context(self, npc_id):
        if npc_id not in NPC_IDS:
            raise ValueError("Unknown NPC")
        room = self.state["actors"][npc_id]["room_id"]
        witnesses = self._actors_at(room)
        promises = [deepcopy(p) for p in self.state["promises"]
                    if p.get("npc_id") == npc_id or p.get("recipient_id") == npc_id
                    or npc_id in p.get("witnesses", []) or npc_id in p.get("actor_ids", [])]
        legal = []
        for aid, spec in ACTIONS.items():
            if not self._action_visible(aid, npc_id):
                continue
            item = self._action_view(aid, npc_id)
            unknown_results = [f for f in spec["provides"] if f in FACTS and self.has(f) and not self.knows(npc_id, f)]
            if unknown_results and room != self._target_room(spec["target_id"]):
                item.update(enabled=False, blocked_reason="需要参与者报告或亲自核实当前现场状态。")
            legal.append(item)
        return {
            "npc_id": npc_id, "name": NAMES[npc_id], "role": NPCS[npc_id]["role"],
            "session_id": self.state["session_id"], "revision": self.state["revision"], "tick": self.state["tick"],
            "room_id": room, "known_facts": self._fact_views(npc_id), "promises": promises,
            "accepted_tasks": list(self.state["social"][npc_id]["accepted_tasks"]),
            "social": deepcopy(self.state["social"][npc_id]), "objectives": [NPCS[npc_id]["goal"]],
            "legal_actions": legal, "witnesses": witnesses,
            "supported_conditions": sorted(SUPPORTED_CONDITIONS),
            "events": [deepcopy(e) for e in self.state["events"] if npc_id in e["witnesses"]][-30:],
            "scene": {"room_id": room, "description": ROOMS[room][1], "smoke": self._smoke(room),
                      "actors": [self._actor_view(a, npc_id) for a in witnesses],
                      "objects": self._objects_in(room), "inventory": self._visible_inventory(npc_id)},
            "player_shareable_facts": self._fact_views("player"),
        }

    def talk_rehearsal(self, npc_id, text, topic_id=""):
        if self.state["mode"] != "rehearsal":
            return self._result(False, "当前是真实AI模式，不能把预设演练当成AI回应。")
        if npc_id not in NPC_IDS or self._target_room(npc_id) != self.state["room_id"]:
            return self._result(False, "请先走到该人物身边。")
        if self.state["execution"] or self.state["ending"]:
            return self._result(False, "当前无法交谈。")
        topic = next((t for t in TOPICS if t["id"] == topic_id and t["npc_id"] == npc_id), None)
        if not topic:
            line = self._say(npc_id, "[离线演练] 此模式只运行明确列出的诊断主题，不理解任意自由文本。请选择主题，或回主菜单创建真实AI会话。", source="rehearsal")
            self._changed()
            return self._result(lines=[line], suggested_steps=[])
        decisions, response, steps = self._rehearsal_topic(npc_id, topic_id)
        errors = []
        for decision in decisions:
            outcome = self.apply_decision(npc_id, decision)
            if not outcome.get("ok"):
                errors.append(outcome.get("error", "条件未满足"))
        if errors:
            response += " 当前规则检查：" + "；".join(errors)
        line = self._say(npc_id, "[离线演练 · 预设主题] " + response, source="rehearsal")
        self._changed()
        return self._result(lines=[line], suggested_steps=steps, suggested_title=topic["label"])

    def _rehearsal_topic(self, npc_id, topic_id):
        """Explicit test fixture, deliberately no keyword/free-text interpretation."""
        decisions, steps = [], []
        def share(*facts):
            decisions.append({"kind": "share_fact", "fact_ids": list(facts), "audience": self._actors_at(self.state["room_id"])})
        def accept(*actions):
            for offset in range(0, len(actions), 12):
                decisions.append({"kind": "accept_task", "action_ids": list(actions[offset:offset + 12]), "conditions": []})
        def step(action_id, actor_id="player", helpers=(), depends=()):
            spec = ACTIONS[action_id]
            steps.append({"id": "s" + str(len(steps) + 1), "action_id": action_id, "actor_id": actor_id,
                          "target_id": spec["target_id"], "helpers": list(helpers), "depends_on": list(depends),
                          "status": "proposed", "reason": "预设诊断方案，仍需规则确认", "duration": spec["duration"]})
        response = "先把可核实的事情分开，再安排谁去执行。"
        if topic_id == "lin_report":
            share("crew_report", "radio_lost", "traffic_unknown")
            response = "司机最后报告电气异常、主电切断，但没有收到邻线封锁确认。我只说了临时停车，担心有人抢开门。之后没有新回报，我不能保证恢复时间。"
        elif topic_id == "lin_help":
            share("crew_report", "traffic_unknown")
            accept(*[aid for aid, spec in ACTIONS.items() if "lin" in spec["actors"]])
            response = "我接受分项核实、清点、整理通道与安全条件成立后的救援任务。交通封锁、步道可走和出口开放要分别确认；收到可靠新消息后，我会更正通报。"
            step("announce_facts", "lin")
            step("clear_aisle", "player")
        elif topic_id == "zhou_child":
            share("child_last_seen", "zhou_tried_door", "door_jammed")
            response = "小满九岁，在05号车厢。我只是去接水；回来发现前门卡住了，才来找工具。我想从外面绕回去，但不知道那条路是否安全。你问我为什么急，这就是原因。"
        elif topic_id == "zhou_help":
            share("child_last_seen", "door_jammed")
            accept(*[aid for aid, spec in ACTIONS.items() if "zhou" in spec["actors"]])
            response = "我愿意和你一起稳住推车、开门、照明和接回孩子。还没检查到她之前，不能只说有人会救她就让我长时间走远。"
            step("clear_trolley", helpers=["zhou"])
            step("free_internal_door", depends=["s1"])
            step("check_child", depends=["s2"])
            step("reunite_child", depends=["s3"])
        elif topic_id == "chen_history":
            share("temporary_fix", "aux_design")
            response = "我曾临时处理那个接头，漏了复测却签了完工。这是我做过的事；现在是不是它出了问题，还得检测。你可以保留记录，我不能把救人和不追问责任绑在一起。"
        elif topic_id == "chen_work":
            share("aux_design", "fixed_phone")
            accept(*[aid for aid, spec in ACTIONS.items() if "chen" in spec["actors"]])
            response = "我接受安全检修和提供技术协助。主灯灭了不能证明辅助支路断电：先隔离并验证，再修复，最后实际复测。说我愿意做，不表示设备已经修好。"
            step("collect_tools", "chen")
            step("isolate_aux", "chen")
            step("inspect_joint", "chen", depends=["s1"])
        elif topic_id == "xu_mother":
            share("mother_stable", "backup_compatible")
            response = "她平时就需要这个设备，现在靠内置电池。备用电源能接通信设备，但要先算清用途、多久送回和剩多少，不能同时接两处。"
        elif topic_id == "xu_loan":
            share("backup_compatible", "mother_stable")
            decisions.append({"kind": "loan", "purpose": "radio", "recipient_id": "player", "deadline_tick": self.state["tick"] + 6, "reserve": 4})
            response = "演练提案是借给你作应急通信，六个行动单位内归还，至少保留四格电；实际交付另行执行。如果新的照护需求使保障不足，我们必须重新安排。"
        elif topic_id == "xu_help":
            share("mother_stable", "backup_compatible")
            accept(*[aid for aid, spec in ACTIONS.items() if "xu" in spec["actors"]])
            response = "我愿意配合照护、关闭隔断和转移。先清好过道，另一名成人和我一起陪母亲过去；离开烟气能减少暴露，但不等于设备从此不用供电。"
            step("clear_aisle")
            step("close_vent", "xu")
            step("move_mother", helpers=["xu"], depends=["s1", "s2"])
        return decisions, response, steps
