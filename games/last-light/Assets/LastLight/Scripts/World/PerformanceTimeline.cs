using System;
using System.Collections.Generic;
using System.Linq;

namespace LastLight
{
    /// <summary>Pure timing/validation logic, shared by runtime playback and deterministic tests.</summary>
    public sealed class PerformanceTimeline
    {
        public static readonly string[] Faces={"neutral","happy","sad","angry","surprised","relieved_smile","concerned","stern","suspicious"};
        public static readonly string[] Actions={"idle","nod","small_nod","shake_head","step_forward","step_back","point","reach_out","cross_arms","open_palms"};
        public static readonly string[] Layers={"full_body","upper_body","additive"};
        public static readonly string[] GazeTargets={"player_head","player_body","away","ground","nearby_threat"};
        public static readonly string[] GazeModes={"direct","soft_focus","avoidant","scanning"};
        public static readonly string[] VoiceStyles={"neutral","warm","soft_restrained","firm","cold","anxious","excited","solemn","wary"};
        public static readonly string[] CoarseEmotions={"neutral","joy","sadness","anger","fear","surprise"};
        public static readonly string[] PrimaryEmotions={"calm","warm","relieved","hopeful","melancholic","hurt","wary","stern","irritated","afraid","shocked","curious","guarded","grateful"};
        public readonly PerformanceView Performance;
        public readonly BodyWindow[] Bodies;
        public readonly FaceCueView[] FacesInOrder;
        public float Duration { get; private set; }
        public int Priority { get; private set; }
        public sealed class BodyWindow
        {
            public BodyCueView cue;
            public int index;
            public float start, duration;
        }
        public PerformanceTimeline(PerformanceView performance,Func<string,float> clipDuration)
        {
            Performance=performance??throw new ArgumentNullException(nameof(performance));
            Validate(performance);
            Duration=Math.Min(5f,Math.Max(.8f,(performance.dialogue?.text?.Length??0)/24f));
            FacesInOrder=(performance.face_cues??Array.Empty<FaceCueView>()).OrderBy(c=>c.start_ms).ToArray();
            Bodies=(performance.body_cues??Array.Empty<BodyCueView>()).Select((cue,index)=>
            {
                float duration=clipDuration(cue.action);
                if(float.IsNaN(duration)||float.IsInfinity(duration)||duration<=0)
                    throw new ArgumentException("Missing animation clip: "+cue.action);
                return new BodyWindow{cue=cue,index=index,start=cue.start_ms/1000f,duration=duration};
            }).OrderBy(w=>w.start).ToArray();
            foreach(var face in FacesInOrder)Duration=Math.Max(Duration,(face.start_ms+face.duration_ms)/1000f);
            foreach(var body in Bodies)
            {
                Duration=Math.Max(Duration,body.start+body.duration);
                Priority=Math.Max(Priority,body.cue.priority);
            }
        }
        public FaceCueView FaceAt(float elapsed)
        {
            FaceCueView current=null;
            foreach(var cue in FacesInOrder)
                if(elapsed>=cue.start_ms/1000f&&elapsed<(cue.start_ms+cue.duration_ms)/1000f)current=cue;
            return current;
        }
        public BodyWindow BodyAt(string layer,float elapsed)
        {
            BodyWindow best=null;
            foreach(var window in Bodies)
            {
                if(window.cue.layer!=layer||elapsed<window.start||elapsed>=window.start+window.duration)continue;
                if(best==null||window.cue.priority>best.cue.priority||
                    (window.cue.priority==best.cue.priority&&window.start>=best.start))best=window;
            }
            return best;
        }
        public static bool CanInterrupt(string policy,int currentPriority,int incomingPriority)
        {
            return policy=="allow_any"||(policy=="allow_higher_priority"&&incomingPriority>currentPriority);
        }
        public static void Validate(PerformanceView performance)
        {
            var faces=performance.face_cues??Array.Empty<FaceCueView>();
            var bodies=performance.body_cues??Array.Empty<BodyCueView>();
            if(faces.Length>6||bodies.Length>6)throw new ArgumentException("Too many performance cues.");
            if(performance.dialogue!=null&&!string.IsNullOrEmpty(performance.dialogue.voice_style)&&!VoiceStyles.Contains(performance.dialogue.voice_style))
                throw new ArgumentException("Invalid voice style.");
            foreach(var cue in faces)
                if(cue==null||!Faces.Contains(cue.preset)||cue.start_ms<0||cue.start_ms>120000||
                    cue.duration_ms<=0||cue.duration_ms>120000||float.IsNaN(cue.intensity)||cue.intensity<0||cue.intensity>1)
                    throw new ArgumentException("Invalid face cue.");
            foreach(var cue in bodies)
                if(cue==null||!Actions.Contains(cue.action)||!Layers.Contains(cue.layer)||
                    cue.start_ms<0||cue.start_ms>120000||cue.priority<0||cue.priority>100)
                    throw new ArgumentException("Invalid body cue.");
            if(performance.gaze!=null&&(!GazeTargets.Contains(performance.gaze.target)||!GazeModes.Contains(performance.gaze.mode)))
                throw new ArgumentException("Invalid gaze.");
            var emotion=performance.emotion;
            if(emotion!=null)
            {
                if(float.IsNaN(emotion.intensity)||emotion.intensity<0||emotion.intensity>1||
                    float.IsNaN(emotion.arousal)||emotion.arousal<0||emotion.arousal>1||
                    float.IsNaN(emotion.valence)||emotion.valence< -1||emotion.valence>1)
                    throw new ArgumentException("Invalid emotion intensity.");
                if(performance.schema_version!="legacy"&&(!CoarseEmotions.Contains(emotion.coarse)||
                    !PrimaryEmotions.Contains(emotion.primary)||(!string.IsNullOrEmpty(emotion.secondary)&&!PrimaryEmotions.Contains(emotion.secondary))))
                    throw new ArgumentException("Invalid v2 emotion enum.");
            }
            string policy=performance.interrupt_policy;
            if(policy!="allow_any"&&policy!="allow_higher_priority"&&policy!="uninterruptible")
                throw new ArgumentException("Invalid interrupt policy.");
        }
        public static PerformanceView ForLine(DialogueLine line)
        {
            if(line.performance!=null)return line.performance;
            string face=Faces.Contains(line.emotion)?line.emotion:"neutral";
            string action=Actions.Contains(line.body_action)?line.body_action:"idle";
            // Legacy/rehearsal presentation is explicit; this never creates dialogue or social facts.
            return new PerformanceView
            {
                schema_version="legacy",npc_id=line.npc_id,turn_id=line.id,
                dialogue=new DialogueView{text=line.text,language="zh-CN",voice_style="neutral"},
                emotion=new EmotionView{primary=face,coarse="neutral",intensity=.5f},
                face_cues=new[]{new FaceCueView{preset=face,intensity=.5f,start_ms=0,duration_ms=1500}},
                body_cues=new[]{new BodyCueView{action=action,layer="upper_body",priority=50,start_ms=0}},
                gaze=new GazeView{target="player_head",mode="soft_focus"},interrupt_policy="allow_any",confidence=1
            };
        }
        public static string FallbackFace(EmotionView emotion)
        {
            if(emotion==null)return "neutral";
            if(Faces.Contains(emotion.primary))return emotion.primary;
            switch(emotion.primary)
            {
                case "calm":case "curious":return "neutral";
                case "warm":case "hopeful":return "happy";
                case "relieved":case "grateful":return "relieved_smile";
                case "melancholic":case "hurt":return "sad";
                case "wary":case "guarded":return "suspicious";
                case "stern":return "stern";
                case "irritated":return "angry";
                case "afraid":return "concerned";
                case "shocked":return "surprised";
            }
            switch(emotion.coarse)
            {
                case "joy":return "happy";case "sadness":return "sad";case "anger":return "angry";
                case "fear":return "concerned";case "surprise":return "surprised";default:return "neutral";
            }
        }
        public static float ReadingSpeed(string voice)
        {
            switch(voice)
            {
                case "warm":return 38;case "soft_restrained":return 32;case "firm":return 44;
                case "cold":return 36;case "anxious":return 46;case "excited":return 48;
                case "solemn":return 32;case "wary":return 34;default:return 42;
            }
        }
    }

    [Serializable] public sealed class PerformanceTrace
    {
        public string line_id,npc_id,event_type,detail;
        public float at;
    }
    public sealed class PerformanceHandle
    {
        public string lineId,npcId,status="queued",error="";
        public bool visualsSkipped,offscreen;
        public bool Released {get;internal set;}
        public float elapsed;
        public PerformanceTimeline timeline;
        internal readonly HashSet<string> marks=new HashSet<string>();
        public bool Started=>status!="queued";
        public bool Finished=>status=="completed"||status=="interrupted"||status=="error";
        public bool Successful=>status=="completed";
    }
}
