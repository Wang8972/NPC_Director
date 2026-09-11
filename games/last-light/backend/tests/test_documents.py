from types import SimpleNamespace

from last_light.director import DirectorBridge
from last_light.engine import WorldEngine


def test_document_is_attributed_notebook_record_not_a_world_fact():
    world = WorldEngine(mode="rehearsal")
    assert world.record_generated_document("report-1", "接应简报", "下一步计划检查设备。", "lin")
    assert not world.has("repair_done") and world.state["tick"] == 0
    assert not world.record_generated_document("report-1", "接应简报", "下一步计划检查设备。", "lin")
    assert len([n for n in world.view()["journal"] if n["kind"] == "document"]) == 1


def test_only_published_public_document_of_delivered_turn_enters_notebook(tmp_path):
    world = WorldEngine(session_id="doc_test", mode="rehearsal")
    def record(cid, visibility="public", status="published", turn="turn-1"):
        return SimpleNamespace(content_id=cid, status=status, turn_id=turn, npc_id="lin",
            candidate=SimpleNamespace(visibility=visibility, title="记录", summary=cid, facts=[]))
    records = [record("allowed"), record("private", "private"), record("staged", status="staged"), record("other-turn", turn="turn-0")]
    store = SimpleNamespace(list_published=lambda sid, npc: records)
    bridge = DirectorBridge(tmp_path, lambda sid: world, lambda sid: None)
    bridge._services["doc_test"] = SimpleNamespace(episodes=SimpleNamespace(content_store=store))
    bridge._record_published_documents("doc_test", "turn-1", "lin")
    assert [n["text"] for n in world.view()["journal"]] == ["allowed"]
