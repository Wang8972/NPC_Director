"""Deterministic action preconditions, results and incident simulation.

No model text is read here. All inputs are registered actions and grounded facts.
"""
from __future__ import annotations

from .content import ACTIONS, ACTOR_IDS, FACTS, NAMES, NPC_IDS, OBJECTS

CHILD_WORK = {"clear_trolley", "free_internal_door", "call_child", "check_child", "reunite_child",
              "assign_child_care", "scout_walkway", "light_walkway", "escort_child", "open_external05"}
COLLECT = {"collect_tools": "tools", "collect_lamp": "lamp", "collect_spares": "spares", "collect_stretcher": "stretcher"}
GIVE = {"give_tools": ("tools", "chen"), "give_spares": ("spares", "chen"), "give_lamp": ("lamp", "lin")}
DUAL = {"clear_trolley", "move_mother", "escort_mother"}


class ActionRules:
    def _action_room(self, step):
        if step["action_id"] == "open_external05":
            return "tunnel"
        return self._target_room(step["target_id"])

    def _action_resources(self, step):
        spec = ACTIONS[step["action_id"]]
        resources = {"actor:" + x for x in [step["actor_id"], *step.get("helpers", [])]}
        if spec["resource"]:
            resources.add("resource:" + spec["resource"])
        if step["action_id"] == "repair_joint":
            resources.add("resource:spares")
        if step["action_id"] in {"move_mother", "escort_mother"}:
            resources.update({"actor:mother", "resource:medical"})
            if self.state["items"]["backup"]["connected_to"] == "medical":
                resources.add("resource:backup")
        if step["action_id"] in {"reunite_child", "escort_child"}:
            resources.add("actor:xiaoman")
        return resources

    def _loan(self):
        return next((p for p in reversed(self.state["promises"]) if p.get("kind") == "loan"), None)

    def _loan_invalid_reason(self, loan, *, taking=False):
        if not loan or loan.get("status") not in ("accepted", "active"):
            return "尚未达成有效借电约定；需要用途、接收人和归还节点。"
        tick = self.state["tick"]
        if tick >= loan["deadline_tick"]:
            return "借用期限已到，需要归还或重新协商。"
        remaining = loan["deadline_tick"] - tick
        charge = self.state["items"]["medical"]["charge"]
        worse = self.state["hazard"]["mother_worse"]
        projected = charge - remaining * (2 if worse else 1)
        if self.state["items"]["medical"]["connected_to"] == "backup":
            return "备用电源正在为照护设备供电，不能同时用于另一设备。"
        if projected < (4 if worse else 2):
            return "预计归还前的照护供电保障不足，请缩短借用或先用替代方案。"
        backup = self.state["items"]["backup"]
        if backup["charge"] < loan.get("reserve", 6) + (3 if taking else 0):
            return "剩余电量不能满足约定的保留量。"
        return ""

    def _check_action(self, step):
        aid = step.get("action_id", "")
        if aid not in ACTIONS:
            return "未登记的行动。"
        spec = ACTIONS[aid]
        actor = step.get("actor_id") or spec["actors"][0]
        helpers = step.get("helpers", [])
        if actor not in spec["actors"] or any(h not in NPC_IDS + ("player",) for h in helpers):
            return "人员不具备这项行动所需的能力。"
        if len(set([actor, *helpers])) != len([actor, *helpers]):
            return "同一人不能同时占据两个协作位置。"
        if step.get("target_id") != spec["target_id"]:
            return "行动对象与已登记的目标不一致。"
        if self.state["ending"]:
            return "救援已经结束。"
        if spec["provides"] and not spec["repeat"] and all(self.has(f) for f in spec["provides"]):
            return "这项工作已经完成，不需要重复消耗时间。"
        participants = [actor, *helpers]
        for required in spec["requires"]:
            if not self.has(required) and not any(self.knows(person, required) for person in participants):
                label = FACTS.get(required, (required, ""))[0]
                return "尚未满足前提：" + label
        target_room = self._action_room(step)
        if not target_room or not self.can_visit(target_room):
            return "尚未建立到行动位置的安全通路。"
        if aid in DUAL and len(participants) < 2:
            return "需要另一名实际参与的成人协助。"
        for person in participants:
            if person in NPC_IDS:
                accepted = self.state["social"][person]["accepted_tasks"]
                if aid not in accepted:
                    return NAMES[person] + "尚未接受这项分工，请先协商。"
                if hasattr(self, "_social_condition_reason"):
                    reason = self._social_condition_reason(person, step)
                    if reason:
                        return reason
            if person == "zhou" and not self.has("child_reunited") and aid not in CHILD_WORK and spec["duration"] > 2:
                delegation = self.state["social"]["zhou"].get("child_delegation")
                if not delegation or delegation.get("status") != "active":
                    return "周屿需要真实的寻人安排和回报节点，才会接受长时间离开。"
            if person == self.state.get("child_caregiver") and self.has("child_reunited") and aid not in {"escort_child", "assign_child_care", "finish_evacuation", "await_rescue", "final_sweep", "count_passengers"}:
                if self.state["actors"]["xiaoman"]["room_id"] != target_room:
                    return "当前陪护人不能把小满独自留在另一车厢，请先交接陪护。"
            if person == self.state.get("mother_caregiver", "xu") and self.state["hazard"]["mother_worse"] and aid not in {"move_mother", "escort_mother"}:
                if self.state["actors"]["mother"]["room_id"] != target_room:
                    return "母亲仍需要现场照护，请先交接或一同转移。"
        resource = spec["resource"]
        if resource in {"tools", "lamp", "spares", "stretcher"} and aid not in COLLECT:
            item = self.state["items"][resource]
            if item["state"] == "consumed":
                return "所需物品已经消耗。"
            if item["holder_id"] not in participants and (item["holder_id"] or item["room_id"] != target_room):
                return item["label"] + "不在执行人或现场；请实际交接，或让持有人协助。"
        if aid in COLLECT and self.state["items"][COLLECT[aid]]["holder_id"]:
            return "物品已被实际领取，不能再生成一份。"
        if aid in GIVE and self.state["items"][GIVE[aid][0]]["holder_id"] != actor:
            return "只有实际持有人可以交出物品。"
        if aid == "take_backup":
            reason = self._loan_invalid_reason(self._loan(), taking=True)
            if reason:
                return reason
            if self._loan()["recipient_id"] != actor:
                return "借用约定的接收人不是这名执行者。"
            if self.state["items"]["backup"]["holder_id"] != "xu":
                return "电源已不在许宁手中，需要按真实位置归还。"
        if aid == "connect_radio":
            reason = self._loan_invalid_reason(self._loan())
            if reason:
                return reason
            if self.state["items"]["backup"]["holder_id"] not in participants or self.state["items"]["backup"]["connected_to"]:
                return "需要实际携带且未连接其他设备的电源。"
        if aid == "radio_request" and not self.has("aux_restored"):
            if self.state["items"]["backup"]["connected_to"] != "radio" or self.state["items"]["backup"]["charge"] < 2:
                return "无线设备没有足够的实际供电，可以改用固定电话。"
            reason = self._loan_invalid_reason(self._loan())
            if reason:
                return reason
        if aid == "disconnect_radio" and self.state["items"]["backup"]["connected_to"] != "radio":
            return "电源目前没有接在通信设备上。"
        if aid == "return_backup":
            item = self.state["items"]["backup"]
            if item["connected_to"]:
                return "先实际断开设备，再运输归还。"
            if item["holder_id"] != actor:
                return "需要由实际持有人归还。"
            if actor == "xu":
                return "电源已经在许宁手中。"
        if aid == "connect_medical":
            item = self.state["items"]["backup"]
            if item["connected_to"] or item["charge"] < 1:
                return "电源已连接其他设备或电量耗尽。"
            if item["holder_id"] not in participants and item["holder_id"] != "xu":
                return "请先让实际持有人把电源送回照护现场。"
        if aid == "disconnect_medical":
            if self.state["items"]["backup"]["connected_to"] != "medical":
                return "照护设备未连接备用电源。"
            if self.state["items"]["medical"]["charge"] < (6 if self.state["hazard"]["mother_worse"] else 3):
                return "内置电量不足以安全接续，不能为借电切断照护。"
        if aid in {"move_mother", "escort_mother"}:
            if self.state["items"]["medical"]["charge"] < 1 and self.state["items"]["backup"]["connected_to"] != "medical":
                return "先保障转移途中的实际供电。"
            if "xu" not in participants and aid not in self.state["social"]["xu"]["accepted_tasks"]:
                return "需要和许宁完成照护交接，或请她参与转移。"
        if aid == "repair_joint":
            spare = self.state["items"]["spares"]
            if spare["state"] == "consumed" or (spare["holder_id"] not in participants and spare["room_id"] != target_room):
                return "密封备件还没有实际送到检修现场。"
        if aid in {"shelter_group", "escort_passengers"} and not self.can_visit("cabin05"):
            return "还不能抵达05号车厢，不能把其中乘客算成已转移。"
        if aid == "reunite_child" and "zhou" not in participants and self.state["actors"]["zhou"]["room_id"] != "cabin07":
            return "周屿不在约定的07会合点，请让他同行或先到07集合。"
        if aid in {"await_rescue", "finish_evacuation"} and self.state.get("sweep_revision", -1) != self.state.get("movement_serial", 0):
            return "人员位置在上次清点后变化了，需要重新做最后检查。"
        return ""

    def _move_person(self, aid, room, x=0.0, z=-.3):
        actor = self.state["actors"][aid]
        if actor["room_id"] != room:
            self.state["movement_serial"] = self.state.get("movement_serial", 0) + 1
        actor.update(room_id=room, x=x, z=z)
        for item in self.state["items"].values():
            if item["holder_id"] == aid and item["connected_to"] in ("", "internal", "medical", "backup"):
                item["room_id"] = room
        if aid == "mother":
            self.state["items"]["medical"]["room_id"] = room
            if self.state["items"]["backup"]["connected_to"] == "medical":
                self.state["items"]["backup"]["room_id"] = room
        if aid == "player":
            self.state["room_id"] = room
            if room not in self.state["visited"]:
                self.state["visited"].append(room)

    def _give_item(self, item_id, person, *, connection=""):
        item = self.state["items"][item_id]
        previous = item["holder_id"]
        if previous in self.state["actors"] and self.state["actors"][previous]["carrying"] == item_id:
            self.state["actors"][previous]["carrying"] = ""
        item.update(holder_id=person, room_id=self.state["actors"][person]["room_id"],
                    connected_to=connection, state="connected" if connection else "held")
        self.state["actors"][person]["carrying"] = item_id

    def _apply_action(self, step):
        aid, person = step["action_id"], step["actor_id"]
        spec = ACTIONS[aid]
        participants = [person, *step.get("helpers", [])]
        room = self._action_room(step)
        obj = OBJECTS.get(step["target_id"], {})
        for i, actor in enumerate(participants):
            self._move_person(actor, room, min(7.2, max(-7.2, obj.get("x", 0) + i*.5)), -.3)
        if aid in COLLECT:
            self._give_item(COLLECT[aid], person)
        elif aid in GIVE:
            self._give_item(GIVE[aid][0], GIVE[aid][1])
        elif aid == "repair_joint":
            spare = self.state["items"]["spares"]
            old = spare["holder_id"]
            if old and self.state["actors"][old]["carrying"] == "spares":
                self.state["actors"][old]["carrying"] = ""
            spare.update(holder_id="", state="consumed")
        elif aid == "take_backup":
            self._give_item("backup", person)
            self._loan()["status"] = "active"
            self._loan()["delivered_tick"] = self.state["tick"]
        elif aid == "connect_radio":
            self._give_item("backup", person, connection="radio")
            self.state["actors"][person]["carrying"] = ""
            self.state["items"]["backup"]["holder_id"] = ""
        elif aid == "disconnect_radio":
            self._give_item("backup", person)
        elif aid == "return_backup":
            destination = self.state["actors"]["xu"]["room_id"]
            self._move_person(person, destination, self.state["actors"]["xu"]["x"]-.6, -.3)
            self._give_item("backup", "xu")
            loan = self._loan()
            if loan:
                loan["returned_tick"] = self.state["tick"]
                loan["status"] = "returned"
        elif aid == "connect_medical":
            self._give_item("backup", "mother", connection="medical")
            self.state["actors"]["mother"]["carrying"] = ""
            self.state["items"]["backup"]["holder_id"] = ""
            self.state["items"]["medical"]["connected_to"] = "backup"
            if self._loan() and self._loan().get("status") in ("accepted", "active", "reclaim_requested"):
                self._loan().update(status="closed_for_care", returned_tick=self.state["tick"])
        elif aid == "disconnect_medical":
            self.state["items"]["medical"]["connected_to"] = "internal"
            self._give_item("backup", person)
        elif aid == "move_mother":
            for i, actor in enumerate([*participants, "mother"]):
                self._move_person(actor, "cabin07", 1+i*.5, 1.3 if actor == "mother" else -.3)
            self.state["mother_caregiver"] = "xu" if "xu" in participants else person
            if self.has("vent_closed"):
                self._add_flag("mother_protected")
                self._learn("mother_protected", participants + ["mother"])
        elif aid == "reunite_child":
            for i, actor in enumerate([*participants, "xiaoman"]):
                self._move_person(actor, "cabin07", 2+i*.4, -.3)
            # The guard required the father to be here or explicitly participating.
            if "zhou" in participants:
                self._move_person("zhou", "cabin07", 3.5, -.3)
            self.state["child_caregiver"] = "zhou"
        elif aid == "assign_child_care":
            self.state["child_caregiver"] = person
        elif aid == "escort_mother":
            for i, actor in enumerate([*participants, "mother"]):
                self._move_person(actor, "tunnel", 2+i*.45, -.2)
            self.state["mother_caregiver"] = "xu" if "xu" in participants else person
        elif aid == "escort_child":
            for i, actor in enumerate([*participants, "xiaoman"]):
                self._move_person(actor, "tunnel", 2+i*.4, -.2)
            self.state["child_caregiver"] = person
            if self.state["actors"]["zhou"]["room_id"] == "tunnel":
                self._add_flag("child_reunited")
                self._learn("child_reunited", self._actors_at("tunnel"))
        elif aid == "escort_passengers":
            self._move_person("passenger05", "tunnel", 3.7, .8)
            self._move_person("passenger07", "tunnel", 4.6, .8)
        elif aid == "shelter_group":
            self._move_person("passenger05", "cabin07", -1, 1.45)
            self._move_person("passenger07", "cabin07", -2.3, 1.45)
        elif aid == "final_sweep":
            self.state["sweep_revision"] = self.state.get("movement_serial", 0)
            self.state["last_sweep"] = {x: a["room_id"] for x, a in self.state["actors"].items()}
        elif aid == "announce_facts":
            self.state["social"]["lin"]["disclosure"] = "qualified"
            known = [f["id"] for f in self.state["knowledge"][person]]
            for fact in ("crew_report", "radio_lost", "traffic_unknown", "traffic_confirmed", "smoke_seen"):
                if fact in known:
                    self._learn(fact, self._actors_at(room), "分项公开通报")
        for flag in spec["provides"]:
            self._add_flag(flag)
        # Only people at the actual location receive results, never everyone in the train.
        witnesses = list(dict.fromkeys([*participants, *self._actors_at(self.state["actors"][person]["room_id"])]))
        facts = [f for f in spec["provides"] if f in FACTS]
        event = self._event("action_completed", spec["label"] + "已实际完成。", witnesses, facts, participants, step["target_id"])
        event["action_id"] = aid
        # Scheduler commits the action just before the final tick's environment update.
        event["tick"] = self.state["tick"] + 1
        for promise in self.state["promises"]:
            if promise.get("kind") == "task" and promise.get("action_id") == aid and promise.get("npc_id") in participants and promise.get("status") == "accepted":
                promise.update(status="fulfilled", fulfilled_tick=self.state["tick"])
        if aid in {"await_rescue", "finish_evacuation"}:
            self._finish("stay_all" if aid == "await_rescue" else "evacuate_all", participants)

    def _advance_time(self, amount):
        interrupted = False
        for _ in range(amount):
            s = self.state
            s["tick"] += 1
            h = s["hazard"]
            if not self.has("aux_isolated"):
                h["heat"] += 1
            elif s["tick"] % 2 == 0:
                h["heat"] = max(0, h["heat"] - 1)  # Residual smoke dissipates, never instantly vanishes.
            if self._smoke("cabin06") and not h["smoke_alerted"]:
                h["smoke_alerted"] = True
                self._event("smoke_first_seen", "06号车厢出现烟气，在场的人提出重新评估等待。",
                            self._actors_at("cabin06"), ["smoke_seen"])
                interrupted = True
            if h["heat"] >= 16 and not h["severe_alerted"]:
                h["severe_alerted"] = True
                self._event("smoke_worsened", "烟气已加重。必须处理热源或完成转移。",
                            self._actors_at("cabin06") + self._actors_at("service"), ["smoke_seen"])
                interrupted = True
            mother_room = s["actors"]["mother"]["room_id"]
            if self._smoke(mother_room):
                h["mother_exposure"] += 1
            elif mother_room in ("cabin07", "tunnel"):
                h["mother_exposure"] = max(0, h["mother_exposure"] - 1)
            if h["mother_exposure"] >= 3 and not h["mother_worse"]:
                h["mother_worse"] = True
                self._event("mother_need_changed", "许母在实际烟气暴露后呼吸变得吃力，设备需要更持续的供电。",
                            self._actors_at(mother_room), ["mother_worse"])
                interrupted = True
            medical, backup = s["items"]["medical"], s["items"]["backup"]
            demand = 2 if h["mother_worse"] else (1 if s["tick"] % 2 == 0 else 0)
            if medical["connected_to"] == "backup" and backup["connected_to"] == "medical":
                backup["charge"] = max(0, backup["charge"] - demand)
                supplied = backup["charge"] > 0 or demand == 0
            else:
                medical["charge"] = max(0, medical["charge"] - demand)
                supplied = medical["charge"] > 0 or demand == 0
            if backup["connected_to"] == "radio":
                backup["charge"] = max(0, backup["charge"] - 1)
            h["unpowered_ticks"] = 0 if supplied else h.get("unpowered_ticks", 0) + 1
            if h["unpowered_ticks"] >= 2 and not h["mother_injured"]:
                h["mother_injured"] = True
                self._event("care_interrupted", "实际供电连续中断，许母的状态受到影响。",
                            self._actors_at(mother_room))
                interrupted = True
            loan = self._loan()
            if loan and loan.get("status") in ("accepted", "active"):
                reason = self._loan_invalid_reason(loan)
                if reason:
                    loan.update(status="reclaim_requested", reclaim_reason=reason, reclaim_tick=s["tick"])
                    self._event("loan_reclaim_requested", "许宁要求重新协商或归还备用电源：" + reason,
                                list(dict.fromkeys(["xu", *self._actors_at(s["actors"]["xu"]["room_id"])])), actor_ids=["xu"], target_id="backup_supply")
                    interrupted = True
            delegation = s["social"]["zhou"].get("child_delegation")
            if delegation and delegation.get("status") == "active" and s["tick"] >= delegation["checkpoint_tick"]:
                if self.knows("zhou", "child_checked") or self.knows("zhou", "child_reunited"):
                    delegation["status"] = "fulfilled"
                else:
                    delegation["status"] = "needs_update"
                    self._event("checkpoint_missed", "约定的寻人回报节点已到，周屿要求先核实进度。",
                                self._actors_at(s["actors"]["zhou"]["room_id"]), actor_ids=["zhou"])
                    interrupted = True
                for promise in s["promises"]:
                    if promise.get("kind") == "child_delegation" and promise.get("plan_id") == delegation.get("plan_id"):
                        promise["status"] = delegation["status"]
            if h["heat"] >= 30 and self._smoke(mother_room) and not self.has("vent_closed"):
                self._finish("failed", [])
                interrupted = True
            if h["unpowered_ticks"] >= 7:
                self._finish("failed", [])
                interrupted = True
        return interrupted

    def _finish(self, requested, participants):
        if self.state["ending"]:
            return
        destination = "cabin07" if requested == "stay_all" else "tunnel"
        # Participants were moved by the explicit final action, never sweep remote adults in here.
        missing = [aid for aid, a in self.state["actors"].items() if a["room_id"] != destination]
        injured = self.state["hazard"]["mother_injured"]
        key = "failed" if requested == "failed" else "costly" if missing or injured else requested
        titles = {"stay_all": "余灯未熄", "evacuate_all": "走向另一束光", "costly": "未尽的回声", "failed": "未能等到的回信"}
        texts = {
            "stay_all": "热源被隔离，清点名单与现场人数相符。救援人员进入07号车厢时，每一个名字都有回应。列车没有继续开走，但你们一起等到了援手。",
            "evacuate_all": "步道上的灯依次亮起。最后一次清点之后，九个人都在避险横通道里。没有一个人靠一句保证被算作获救。",
            "costly": "求援得到了回应，但这份名单仍留下需要面对的代价。" + ("尚未抵达安全点：" + "、".join(NAMES[x] for x in missing) + "。" if missing else "许母因供电中断受到伤害。"),
            "failed": "未处理的危险超出了现场能够维持的条件。记录停在最后一次确认的行动；没有人能用后来的解释改写已经发生的后果。",
        }
        self.state.update(ending=key, ending_title=titles[key], ending_text=texts[key])
        loan = self._loan()
        epilogues = {
            "lin": "林岚把逐项通报和交接记录留了下来。" if self.has("facts_announced") else "林岚保留了收到的岗位消息；你没有在这次救援中核实全部内容。",
            "zhou": "周屿握住小满的手。水杯早已空了，他仍记得是谁带来了第一条可靠消息。" if self.state["actors"]["xiaoman"]["room_id"] == self.state["actors"]["zhou"]["room_id"] and self.has("child_checked") else "关于小满的最后一条可靠消息仍被保留，没有被一句安慰改写成团聚。",
            "chen": ("陈默完成了这一次复测。" if self.has("retest_passed") else "现场设备状态已被如实记录，尚未完成的工作不会被写成成功。") + ("真实检修记录已保存，调查可以继续。" if self.knows("player", "maintenance_record") else "关于维护经过，你没有获得足以作出结论的材料。"),
            "xu": ("许宁记得你们及时把母亲带离了烟气。" if not self.state["hazard"]["mother_worse"] else "许宁记得，母亲状况变化后，原来的承诺需要被重新理解。") + ("备用电源按真实交接回到了她手里。" if loan and loan.get("status") == "returned" else "电源的去向与剩余电量被如实记下。"),
        }
        self.state["epilogues"] = [{"id": self._id("epilogue"), "npc_id": npc, "speaker": NAMES[npc], "text": text,
                                    "emotion": "relieved_smile" if key.endswith("all") else "concerned", "source": "narrative"}
                                   for npc, text in epilogues.items()]
        self._event("rescue_ended", titles[key], self._actors_at(self.state["room_id"]))
