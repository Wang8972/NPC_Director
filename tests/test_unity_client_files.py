from pathlib import Path

ROOT = Path("unity/NPCDirectorClient")


def read(name: str) -> str:
    return (ROOT / "Scripts" / name).read_text(encoding="utf-8")


def test_unity_client_contains_bidirectional_protocol_and_reconnect() -> None:
    client = read("NPCDirectorClient.cs")

    assert '"turn.request"' in read("NpcDirectorMessages.cs")
    assert '"performance.plan"' in client
    assert '"performance.{eventType}"' in client
    assert "ConnectLoopAsync" in client
    assert "ClientWebSocket" in client
    assert "outgoingMessages" in client
    assert "thinkingState" in client
    assert 'header.type == "error"' in client
    assert "ErrorEnvelope" in read("NpcDirectorMessages.cs")
    assert 'schema_version != "1.0"' in client
    assert "session_id != sessionId" in client
    assert "npcRegistry.TryResolve" in client
    assert "unknown npc_id" in client


def test_executor_has_local_idempotency_and_all_feedback_events() -> None:
    executor = read("PerformanceExecutor.cs")

    assert "HashSet<string> completedKeys" in executor
    assert "PlayerPrefs" in executor
    for event in ("ack", "started", "completed", "interrupted"):
        assert f'"{event}"' in executor
    assert "interrupt_policy" in executor
    assert "CanInterrupt(activeInterruptPolicy, incomingPriority)" in executor
    assert "incomingPriority > activePriority" in executor
    assert "activeKey == plan.idempotency_key" in executor
    assert '"duplicate_in_flight"' in executor
    assert "ValidateDirective" in executor


def test_unity_actions_and_faces_are_allowlisted_without_reflection() -> None:
    action_catalog = read("ActionCatalog.cs")
    face_controller = read("FacialPresetController.cs")
    combined = action_catalog + face_controller + read("PerformanceExecutor.cs")

    for action in ("idle", "nod", "shake_head", "step_forward", "point"):
        assert f'"{action}"' in action_catalog
    for preset in ("neutral", "happy", "sad", "angry", "surprised"):
        assert f'"{preset}"' in face_controller
    assert "System.Reflection" not in combined
    assert "Type.GetType" not in combined
    assert "InvokeMember" not in combined


def test_unity_assembly_excludes_webgl_client_websocket() -> None:
    assembly = (ROOT / "NPCDirectorClient.asmdef").read_text(encoding="utf-8")

    assert '"WebGL"' in assembly


def test_prototype_spike_client_has_registry_and_snapshot_guards() -> None:
    registry = read("NpcRegistry.cs")
    snapshots = read("PrototypeSceneStateController.cs")
    runner = read("PrototypeSnapshotSpikeRunner.cs")

    for npc_id in ("guard_captain_maren", "mechanic_lia", "porter_finn"):
        assert npc_id in registry
    assert "UnknownRouteCount" in registry
    assert "[S1_SUMMARY]" in registry
    assert "snapshot.world_version < lastWorldVersion" in snapshots
    assert "snapshot.world_version == lastWorldVersion" in snapshots
    assert "CanonicalObjectIds" in snapshots
    assert "[S3_SUMMARY]" in runner
    assert "resetHashMatches" in runner
