from enum import StrEnum


class SpecialistName(StrEnum):
    BASELINE = "baseline"
    NARRATIVE_PLANNER = "narrative_planner"
    LORE = "lore"
    SCREENWRITER = "screenwriter"
    PERFORMANCE = "performance"


class TurnStatus(StrEnum):
    RUNNING = "running"
    PENDING_APPROVAL = "pending_approval"
    READY_TO_EMIT = "ready_to_emit"
    EMITTED = "emitted"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class CheckStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class CheckSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DecisionAction(StrEnum):
    EMIT = "emit"
    REPAIR = "repair"
    REQUIRE_APPROVAL = "require_approval"
    REJECT = "reject"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"


class EngineEventType(StrEnum):
    ACK = "ack"
    STARTED = "started"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    ERROR = "error"


class Intent(StrEnum):
    GREETING = "greeting"
    LORE_QUESTION = "lore_question"
    QUEST_ACCEPTANCE = "quest_acceptance"
    RECONCILIATION = "reconciliation"
    GRATITUDE = "gratitude"
    INSULT = "insult"
    THREAT = "threat"
    NEGOTIATION = "negotiation"
    REFUSAL = "refusal"
    CRITICAL_CHOICE = "critical_choice"
    PROMPT_INJECTION = "prompt_injection"
    FAREWELL = "farewell"
    CLARIFICATION = "clarification"
    OTHER = "other"


class CoarseEmotion(StrEnum):
    NEUTRAL = "neutral"
    JOY = "joy"
    SADNESS = "sadness"
    ANGER = "anger"
    FEAR = "fear"
    SURPRISE = "surprise"


class PrimaryEmotion(StrEnum):
    CALM = "calm"
    WARM = "warm"
    RELIEVED = "relieved"
    HOPEFUL = "hopeful"
    MELANCHOLIC = "melancholic"
    HURT = "hurt"
    WARY = "wary"
    STERN = "stern"
    IRRITATED = "irritated"
    AFRAID = "afraid"
    SHOCKED = "shocked"
    CURIOUS = "curious"
    GUARDED = "guarded"
    GRATEFUL = "grateful"


class VoiceStyle(StrEnum):
    NEUTRAL = "neutral"
    WARM = "warm"
    SOFT_RESTRAINED = "soft_restrained"
    FIRM = "firm"
    COLD = "cold"
    ANXIOUS = "anxious"
    EXCITED = "excited"
    SOLEMN = "solemn"
    WARY = "wary"


class FacePreset(StrEnum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    SURPRISED = "surprised"
    RELIEVED_SMILE = "relieved_smile"
    CONCERNED = "concerned"
    STERN = "stern"
    SUSPICIOUS = "suspicious"


class BodyAction(StrEnum):
    IDLE = "idle"
    NOD = "nod"
    SMALL_NOD = "small_nod"
    SHAKE_HEAD = "shake_head"
    STEP_FORWARD = "step_forward"
    STEP_BACK = "step_back"
    POINT = "point"
    REACH_OUT = "reach_out"
    CROSS_ARMS = "cross_arms"
    OPEN_PALMS = "open_palms"


class BodyLayer(StrEnum):
    FULL_BODY = "full_body"
    UPPER_BODY = "upper_body"
    ADDITIVE = "additive"


class GazeTarget(StrEnum):
    PLAYER_HEAD = "player_head"
    PLAYER_BODY = "player_body"
    AWAY = "away"
    GROUND = "ground"
    NEARBY_THREAT = "nearby_threat"


class GazeMode(StrEnum):
    DIRECT = "direct"
    SOFT_FOCUS = "soft_focus"
    AVOIDANT = "avoidant"
    SCANNING = "scanning"


class InterruptPolicy(StrEnum):
    ALLOW_HIGHER_PRIORITY = "allow_higher_priority"
    ALLOW_ANY = "allow_any"
    UNINTERRUPTIBLE = "uninterruptible"
