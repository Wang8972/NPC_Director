using System;

namespace LastLight
{
    // This wire model deliberately matches the authoritative Python projection.
    // Incoming DTOs use GameJson to preserve null execution/job/performance objects.
    [Serializable] public sealed class GameView
    {
        public string session_id, mode, room_id, objective, chapter, ending, ending_title, ending_text;
        public int revision, tick;
        public ActorView[] actors = Array.Empty<ActorView>();
        public RoomView[] rooms = Array.Empty<RoomView>();
        public ObjectView[] objects = Array.Empty<ObjectView>();
        public ActionView[] actions = Array.Empty<ActionView>();
        public ItemView[] inventory = Array.Empty<ItemView>();
        public JournalView[] journal = Array.Empty<JournalView>();
        public DialogueLine[] dialogue = Array.Empty<DialogueLine>();
        public PlanView[] plans = Array.Empty<PlanView>();
        public TopicView[] topics = Array.Empty<TopicView>();
        public ExecutionView execution;
        public DialogueLine[] epilogues = Array.Empty<DialogueLine>();
    }

    [Serializable] public sealed class ActorView
    {
        public string id, name, role, room_id, pose, emotion, carrying, task_status;
        public string activity, attention_target_id, health_display;
        public string[] companions = Array.Empty<string>();
        public float x, z;
    }
    [Serializable] public sealed class RoomView
    {
        public string id, title, description, lighting, exit_via;
        public bool accessible, direct_accessible, visited;
        public int smoke;
    }
    [Serializable] public sealed class ObjectView
    {
        public string id, label, room_id, state, description;
        public bool interactable;
        public float x, z;
    }
    [Serializable] public sealed class ActionView
    {
        public string id, label, description, target_id, kind, blocked_reason, default_actor;
        public int duration;
        public bool enabled;
        public string[] actor_ids = Array.Empty<string>();
    }
    [Serializable] public sealed class ItemView
    {
        public string id, label, owner_id, holder_id, room_id, connected_to, state, visual_state;
        public int charge = -1;
    }
    [Serializable] public sealed class JournalView
    {
        public string id, title, text, source, kind;
        public int tick;
    }
    [Serializable] public sealed class DialogueLine
    {
        public string id, npc_id, speaker, text, emotion, source, body_action;
        public PerformanceView performance;
        public string playback_status, delivery_status;
        public bool delivered, visuals_skipped, legacy;
    }
    [Serializable] public sealed class PlanStep
    {
        public string id, action_id, actor_id, target_id, status, reason;
        public string[] helpers = Array.Empty<string>();
        public string[] depends_on = Array.Empty<string>();
        public int duration;
        public int remaining = -1;
        public ActionPresentationView presentation;
        public string visible_target_id, source_id, destination_id, source_room_id, destination_room_id;
        public string[] item_ids = Array.Empty<string>();
        public string[] participant_ids = Array.Empty<string>();
    }
    [Serializable] public sealed class PlanView
    {
        public string id, title, status, summary;
        public int total_ticks;
        public string[] conditions = Array.Empty<string>();
        public PlanStep[] steps = Array.Empty<PlanStep>();
    }
    [Serializable] public sealed class ExecutionView
    {
        public string id, plan_id, action_id, target_id, room_id;
        public string[] actor_ids = Array.Empty<string>();
        public int duration;
        public PlanStep[] steps = Array.Empty<PlanStep>();
    }
    [Serializable] public sealed class TopicView { public string id, npc_id, label, description; }
    [Serializable] public sealed class TalkJob
    {
        public string id, status, error, source, episode_id, suggested_title;
        public DialogueLine[] lines = Array.Empty<DialogueLine>();
        public PlanStep[] suggested_steps = Array.Empty<PlanStep>();
    }
    [Serializable] public sealed class SessionInfo { public string session_id, updated_at, chapter, mode; public int tick; }
    [Serializable] public sealed class ApiResponse
    {
        public bool ok;
        public bool director_ready;
        public string error, session_id, app_id;
        public GameView view;
        public TalkJob job;
        public SessionInfo[] sessions = Array.Empty<SessionInfo>();
        [NonSerialized] public bool network_error;
        [NonSerialized] public long http_status;
    }
    [Serializable] public sealed class CreateSessionRequest { public string mode; }
    [Serializable] public class RevisionRequest { public int expected_revision; }
    [Serializable] public sealed class MoveRequest : RevisionRequest { public string room_id; }
    [Serializable] public sealed class InspectRequest : RevisionRequest { public string target_id; }
    [Serializable] public sealed class PlanStepRequest
    {
        public string id, action_id, actor_id, target_id;
        public string[] helpers = Array.Empty<string>();
        public string[] depends_on = Array.Empty<string>();
    }
    [Serializable] public sealed class PlanRequest : RevisionRequest { public string title; public PlanStepRequest[] steps; }
    [Serializable] public sealed class PlanIdRequest : RevisionRequest { public string plan_id; }
    [Serializable] public sealed class CompleteRequest : RevisionRequest { public string execution_id; }
    [Serializable] public sealed class TalkRequest : RevisionRequest
    {
        public string npc_id, text, topic_id;
        public string[] audience = Array.Empty<string>();
    }
    [Serializable] public sealed class AckRequest { public string line_id; }
    [Serializable] public sealed class PerformanceEventRequest
    {
        public string line_id, event_id, event_type;
        public bool visuals_skipped;
    }
    [Serializable] public sealed class PerformanceView
    {
        public string schema_version, session_id, turn_id, npc_id, interrupt_policy;
        public DialogueView dialogue;
        public EmotionView emotion;
        public FaceCueView[] face_cues = Array.Empty<FaceCueView>();
        public BodyCueView[] body_cues = Array.Empty<BodyCueView>();
        public GazeView gaze;
        public float confidence;
    }
    [Serializable] public sealed class DialogueView { public string text, language, voice_style; }
    [Serializable] public sealed class EmotionView
    {
        public string coarse, primary, secondary;
        public float intensity, valence, arousal;
    }
    [Serializable] public sealed class FaceCueView
    {
        public string preset;
        public float intensity;
        public int start_ms, duration_ms;
    }
    [Serializable] public sealed class BodyCueView
    {
        public string action, layer;
        public int priority, start_ms;
    }
    [Serializable] public sealed class GazeView { public string target, mode; }
    [Serializable] public sealed class ActionPresentationView
    {
        public string action_id, visual_kind, preparation_clip, result_clip, failed_clip;
        public string[] resource_ids = Array.Empty<string>();
        public string[] socket_ids = Array.Empty<string>();
        public string[] participant_roles = Array.Empty<string>();
    }
}
