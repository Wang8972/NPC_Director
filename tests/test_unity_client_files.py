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


def test_p1_graybox_has_local_state_rules_and_both_routes() -> None:
    state = read("PrototypeWorldState.cs")
    rules = read("PrototypePuzzleRules.cs")
    runner = read("PrototypeP1GateRunner.cs")

    for npc_id in ("guard_captain_maren", "mechanic_lia", "porter_finn"):
        assert npc_id in rules
    for object_id in (
        "gate_console",
        "generator",
        "control_cabinet",
        "cargo_crate_c12",
        "manifest_board",
        "alarm_lamp",
    ):
        assert object_id in state
    for objective in (
        "investigate_fault",
        "find_fuse",
        "install_fuse",
        "restart_gate",
        "prototype_success",
    ):
        assert objective in state + rules
    assert '"cooperation"' in rules
    assert '"procedure"' in rules
    assert '"diagnose_generator"' not in state + rules
    assert "PendingRoute" not in state + rules
    assert "RunCooperationRoute" in runner
    assert "RunProcedureRoute" in runner
    assert '"[P1_SUMMARY]' in runner
    assert "backendClientCount == 0" in runner
    assert "ClientWebSocket" not in state + rules


def test_p1_graybox_has_npc_selection_hotspots_ui_and_reset() -> None:
    controller = read("PrototypeGameFlowController.cs")
    hotspot = read("PrototypeHotspot.cs")
    selector = read("PrototypeNpcSelector.cs")
    ui_action = read("PrototypeUiAction.cs")
    editor = (ROOT / "Editor" / "PrototypeP1SceneBuilder.cs").read_text(encoding="utf-8")
    editor_assembly = (ROOT / "Editor" / "NPCDirectorClient.Editor.asmdef").read_text(
        encoding="utf-8"
    )

    assert "HandleHotspot" in controller
    assert "SelectNpc" in controller
    assert "ResetPrototype" in controller
    assert "feedbackText" in controller
    assert "clueText" in controller
    assert "OnMouseDown" in hotspot
    assert "OnMouseDown" in selector
    assert "ExecuteUiCommand" in ui_action
    assert 'MenuItem("NPC Director/P1/Create or Reset Graybox Scene")' in editor
    assert 'ScenePath = "Assets/Scenes/PrototypeGateRepairP1.unity"' in editor
    assert "CreateNpcs(flow)" in editor
    assert "CreateEnvironment(flow)" in editor
    assert '"backend_clients=0"' in editor
    assert '"Editor"' in editor_assembly
