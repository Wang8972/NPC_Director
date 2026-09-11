"""Authoritative train world. Presentation and model text never commit physics."""
from __future__ import annotations

from copy import deepcopy

from .content import ACTIONS, ACTOR_IDS, FACTS, NAMES, NPC_IDS, NPCS, OBJECTS, ROOMS, TOPICS
from .models import new_state, validate_state
from .projection import Projection
from .rules_actions import ActionRules
from .scheduler import PlanRules
from .social_rules import SocialRules


class WorldEngine(PlanRules, SocialRules, Projection, ActionRules):
    def __init__(self, state: dict | None = None, session_id: str | None = None, mode: str = "live"):
        self.state = validate_state(state) if state is not None else new_state(session_id, mode)
        if state is None:
            self._say("narrator", "列车在长隧道里骤然停住。应急灯亮起，林岚守在广播旁；周屿攥着水杯，要求打开外门。你是07号车厢的一名普通乘客。")
            self._event("arrival", "异常停车。先观察车厢，听听在场的人掌握了什么。", ["player", "lin", "zhou", "passenger07"])

    def _id(self, prefix: str) -> str:
        value = f"{prefix}_{self.state['next_id']}"
        self.state["next_id"] += 1
        return value

    def has(self, flag: str) -> bool:
        return flag in self.state["flags"]

    def knows(self, actor_id: str, fact_id: str) -> bool:
        return any(f["id"] == fact_id for f in self.state["knowledge"].get(actor_id, []))

    def _add_flag(self, flag: str):
        if not self.has(flag):
            self.state["flags"].append(flag)

    def _actors_at(self, room_id: str) -> list[str]:
        return [aid for aid, actor in self.state["actors"].items() if actor["room_id"] == room_id]

    def _learn(self, fact_id: str, actor_ids, source="现场观察", quality="verified"):
        if fact_id not in FACTS:
            return
        if isinstance(actor_ids, str):
            actor_ids = [actor_ids]
        rank = {"reported": 0, "observed": 1, "verified": 2}
        for aid in dict.fromkeys(actor_ids):
            if aid not in ACTOR_IDS:
                continue
            records = self.state["knowledge"][aid]
            old = next((f for f in records if f["id"] == fact_id), None)
            record = {"id": fact_id, "source": source, "quality": quality, "tick": self.state["tick"]}
            if old is None:
                records.append(record)
            elif rank[quality] > rank[old["quality"]]:
                old.update(record)
            else:
                continue
            if aid == "player":
                title, text = FACTS[fact_id]
                self.state["journal"].append({"id": self._id("note"), "title": title, "text": text, "source": source, "kind": quality, "tick": self.state["tick"]})

    def _event(self, kind: str, text: str, witnesses=None, fact_ids=None, actor_ids=None, target_id=""):
        event = {"id": self._id("event"), "kind": kind, "text": text, "tick": self.state["tick"],
                 "witnesses": list(dict.fromkeys(witnesses or [])), "fact_ids": list(fact_ids or []),
                 "actor_ids": list(actor_ids or []), "target_id": target_id}
        self.state["events"].append(event)
        for fid in event["fact_ids"]:
            self._learn(fid, event["witnesses"], source="现场事件")
        return event

    def _say(self, npc_id: str, text: str, source="narrative", emotion="neutral", line_id=None):
        line = {"id": line_id or self._id("line"), "npc_id": npc_id, "speaker": NAMES.get(npc_id, "现场"),
                "text": text, "emotion": emotion, "source": source}
        self.state["dialogue"].append(line)
        return line

    def _result(self, ok=True, error="", **extra):
        return {"ok": ok, "error": error, "view": self.view(), **extra}

    def _changed(self):
        self.state["revision"] += 1

    def record_generated_document(self, content_id, title, text, author):
        """A published document is an attributed record, not a new physical fact."""
        note_id = "document:" + str(content_id)
        if any(note["id"] == note_id for note in self.state["journal"]):
            return False
        if author not in NPC_IDS or not title or not text:
            raise ValueError("文书缺少有效作者或内容。")
        self.state["journal"].append({"id": note_id, "title": str(title)[:200],
            "text": str(text)[:2400], "source": NAMES[author] + "整理的已审核文书（不自动证明新的世界事实）",
            "kind": "document", "tick": self.state["tick"]})
        self._changed()
        return True

    def _target_room(self, target_id):
        if target_id in self.state["actors"]:
            return self.state["actors"][target_id]["room_id"]
        if target_id == "oxygen":
            return self.state["actors"]["mother"]["room_id"]
        if target_id == "backup_supply":
            return self.state["items"]["backup"]["room_id"]
        if target_id == "child":
            return self.state["actors"]["xiaoman"]["room_id"]
        return OBJECTS.get(target_id, {}).get("room_id", "")

    def can_visit(self, room_id: str) -> bool:
        if room_id not in ROOMS:
            return False
        if room_id == "cabin05":
            return self.has("inner_door_open") or (self.has("external05_open") and self.has("outer_open"))
        if room_id == "tunnel":
            return all(self.has(f) for f in ("traffic_confirmed", "path_surveyed", "outer_open"))
        return True

    def move(self, room_id: str) -> dict:
        if self.state["execution"]:
            return self._result(False, "执行尚未结算，请先完成或取消。")
        if self.state["ending"]:
            return self._result(False, "本次救援已经结束。")
        if not self.can_visit(room_id):
            return self._result(False, "通路尚未实际打开，或车外安全条件尚未逐项核实。")
        if self.state["room_id"] == room_id:
            return self._result()
        self.state["room_id"] = room_id
        self.state["actors"]["player"].update(room_id=room_id, x=0, z=-.3)
        for item in self.state["items"].values():
            if item["holder_id"] == "player" and not item["connected_to"]:
                item["room_id"] = room_id
        if room_id not in self.state["visited"]:
            self.state["visited"].append(room_id)
        if self._smoke(room_id):
            self._learn("smoke_seen", ["player"], "亲眼观察", "observed")
        self._changed()
        return self._result()

    def inspect(self, target_id: str) -> dict:
        if self.state["execution"]:
            return self._result(False, "执行中无法同时调查。")
        if self.state["ending"]:
            return self._result(False, "本次救援已经结束。")
        if target_id not in OBJECTS and target_id not in NPC_IDS:
            return self._result(False, "没有可调查的对象。")
        exterior05 = target_id == "outer_door05" and self.state["room_id"] == "tunnel"
        if self._target_room(target_id) != self.state["room_id"] and not exterior05:
            return self._result(False, "需要先走到对象所在的车厢。")
        if target_id in self.state["inspected"]:
            return self._result()
        if target_id in NPC_IDS:
            text = {
                "lin": "林岚反复查看对讲机，视线始终没有离开外门和过道。",
                "zhou": "周屿攥着半杯水，来回望向06号车厢，像是在计算还要耽搁多久。",
                "chen": "陈默站在控制箱旁，先查看指示灯，没有直接伸手接触设备。",
                "xu": "许宁坐在母亲与备用电源之间，留意设备的灯和母亲的呼吸。",
            }[target_id]
            facts = []
            label = NAMES[target_id]
        else:
            obj = OBJECTS[target_id]
            text, facts, label = obj["description"], obj["facts"], obj["label"]
            if exterior05:
                text = "步道上的05号外门释放口有清楚标识；只能看到门外结构，里面的人员与伤情仍需进入后核实。"
        self.state["inspected"].append(target_id)
        self.state["journal"].append({"id": self._id("note"), "title": label, "text": text,
                                     "source": "亲眼调查", "kind": "observed", "tick": self.state["tick"]})
        for fid in facts:
            self._learn(fid, ["player"], "亲眼调查", "observed")
        self._say("narrator", text)
        self._changed()
        return self._result()

    def _smoke(self, room_id: str) -> int:
        heat = self.state["hazard"]["heat"]
        level = 2 if heat >= 16 else 1 if heat >= 6 else 0
        if room_id in ("service", "cabin06"):
            return level
        if room_id == "cabin07" and not self.has("vent_closed"):
            return max(0, level - 1)
        return 0
