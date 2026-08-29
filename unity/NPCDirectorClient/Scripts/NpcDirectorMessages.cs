using System;

namespace NPCDirector
{
    [Serializable]
    public sealed class MessageHeader
    {
        public string message_id;
        public string type;
    }

    [Serializable]
    public sealed class TurnRequestEnvelope
    {
        public string message_id;
        public string type = "turn.request";
        public TurnRequestPayload payload;
    }

    [Serializable]
    public sealed class TurnRequestPayload
    {
        public string session_id;
        public string turn_id;
        public string npc_id;
        public string player_input;
        public SceneSnapshot scene;
        public string character_core;
        public string[] recent_history = Array.Empty<string>();
        public string world_state_summary = "";
    }

    [Serializable]
    public sealed class SceneSnapshot
    {
        public string location;
        public float tension;
        public string[] nearby_entities = Array.Empty<string>();
        public string animator_state = "idle";
        public string[] active_actions = Array.Empty<string>();
        public string catalog_version = "m0-v1";
    }

    [Serializable]
    public sealed class PerformancePlanEnvelope
    {
        public string message_id;
        public string type;
        public PerformancePlanPayload payload;
    }

    [Serializable]
    public sealed class PerformancePlanPayload
    {
        public PerformanceDirective directive;
        public string idempotency_key;
    }

    [Serializable]
    public sealed class PerformanceDirective
    {
        public string schema_version;
        public string session_id;
        public string turn_id;
        public string npc_id;
        public Dialogue dialogue;
        public Emotion emotion;
        public FaceCue[] face_cues = Array.Empty<FaceCue>();
        public BodyCue[] body_cues = Array.Empty<BodyCue>();
        public GazeDirective gaze;
        public string interrupt_policy;
        public float confidence;
        public Evidence evidence;
        public RuntimeMeta runtime_meta;
    }

    [Serializable]
    public sealed class Dialogue
    {
        public string text;
        public string language;
        public string voice_style;
    }

    [Serializable]
    public sealed class Emotion
    {
        public string coarse;
        public string primary;
        public string secondary;
        public float intensity;
        public float valence;
        public float arousal;
    }

    [Serializable]
    public sealed class FaceCue
    {
        public string preset;
        public float intensity;
        public int start_ms;
        public int duration_ms;
    }

    [Serializable]
    public sealed class BodyCue
    {
        public string action;
        public string layer;
        public int priority;
        public int start_ms;
    }

    [Serializable]
    public sealed class GazeDirective
    {
        public string target;
        public string mode;
    }

    [Serializable]
    public sealed class Evidence
    {
        public string[] lore_refs = Array.Empty<string>();
    }

    [Serializable]
    public sealed class RuntimeMeta
    {
        public string[] specialists_called = Array.Empty<string>();
        public string[] prompt_versions = Array.Empty<string>();
        public string model;
        public string trace_id;
        public string response_id;
    }

    [Serializable]
    public sealed class PerformanceEventEnvelope
    {
        public string message_id;
        public string type;
        public PerformanceEventPayload payload;
    }

    [Serializable]
    public sealed class PerformanceEventPayload
    {
        public string session_id;
        public string turn_id;
        public string idempotency_key;
        public string event_type;
        public string detail;
        public string occurred_at;
    }

    [Serializable]
    public sealed class SceneObserveRequestEnvelope
    {
        public string message_id;
        public string type = "scene.observe.request";
        public SceneObserveRequestPayload payload;
    }

    [Serializable]
    public sealed class SceneObserveRequestPayload
    {
        public string session_id;
        public string request_id;
        public string object_id;
        public int expected_world_version;
    }

    [Serializable]
    public sealed class SceneActionPlanEnvelope
    {
        public string message_id;
        public string type = "scene.action.plan";
        public SceneActionPlanPayload payload;
    }

    [Serializable]
    public sealed class SceneActionPlanPayload
    {
        public SceneActionCommand action;
        public PerformanceDirective pre_commit_directive;
        public string idempotency_key;
    }

    [Serializable]
    public sealed class SceneActionCommand
    {
        public string schema_version;
        public string session_id;
        public string turn_id;
        public string action_id;
        public string actor_id;
        public string action_type;
        public string object_id;
        public string item_id;
        public string target_id;
        public string target_npc_id;
        public string operation;
        public int basis_world_version;
    }

    [Serializable]
    public sealed class SceneActionEventEnvelope
    {
        public string message_id;
        public string type;
        public SceneActionEventPayload payload;
    }

    [Serializable]
    public sealed class SceneActionEventPayload
    {
        public string session_id;
        public string turn_id;
        public string action_id;
        public string idempotency_key;
        public string event_type;
        public string detail;
        public string occurred_at;
    }

    [Serializable]
    public sealed class WorldEventEnvelope
    {
        public string message_id;
        public string type = "world.event";
        public WorldEventPayload payload;
    }

    [Serializable]
    public sealed class WorldEventPayload
    {
        public string session_id;
        public string event_id;
        public string event_type;
        public int world_version;
        public string summary;
        public string[] revealed_fact_ids = Array.Empty<string>();
    }

    [Serializable]
    public sealed class PrototypeResetRequestEnvelope
    {
        public string message_id;
        public string type = "prototype.reset.request";
        public PrototypeResetRequestPayload payload;
    }

    [Serializable]
    public sealed class PrototypeResetRequestPayload
    {
        public string session_id;
        public string reset_token;
    }

    [Serializable]
    public sealed class ErrorEnvelope
    {
        public string message_id;
        public string type;
        public ErrorPayload payload;
    }

    [Serializable]
    public sealed class ErrorPayload
    {
        public string code;
        public string message;
        public string turn_id;
    }

    [Serializable]
    public sealed class StateSnapshotEnvelope
    {
        public string message_id;
        public string type = "state.snapshot";
        public PrototypeStateSnapshotPayload payload;
    }

    [Serializable]
    public sealed class PrototypeStateSnapshotPayload
    {
        public string session_id;
        public string scene_id;
        public int world_version;
        public string objective_state;
        public PrototypeObjectState[] object_states = Array.Empty<PrototypeObjectState>();
        public PrototypeItemLocation[] item_locations = Array.Empty<PrototypeItemLocation>();
        public string[] discovered_fact_ids = Array.Empty<string>();
        public PrototypeRouteFlags route_flags = new PrototypeRouteFlags();
        public PrototypePendingAction pending_action;
    }

    [Serializable]
    public sealed class PrototypeObjectState
    {
        public string object_id;
        public string state;
    }

    [Serializable]
    public sealed class PrototypeItemLocation
    {
        public string item_id;
        public string location_id;
    }

    [Serializable]
    public sealed class PrototypeRouteFlags
    {
        public string fuse_route = "none";
        public bool crate_c12_authorized;
        public bool control_cabinet_authorized;
    }

    [Serializable]
    public sealed class PrototypePendingAction
    {
        public string action_id;
        public string actor_id;
        public string action_type;
        public int basis_world_version;
    }
}
