using System;
using System.Collections.Generic;

namespace LastLight.QA
{
    /// <summary>Deterministic checks of real scheduler code. No Unity scene, backend or model is required.</summary>
    public static class PresentationContractChecks
    {
        public static int AssertionCount {get;private set;}
        public static string[] Run()
        {
            AssertionCount=0;
            var failures=new List<string>();
            Action<bool,string> check=(ok,message)=>{AssertionCount++;if(!ok)failures.Add(message);};
            var performance=Base();
            performance.face_cues=new[]{
                new FaceCueView{preset="neutral",intensity=.3f,start_ms=0,duration_ms=1000},
                new FaceCueView{preset="concerned",intensity=.8f,start_ms=200,duration_ms=400}};
            performance.body_cues=new[]{
                new BodyCueView{action="nod",layer="upper_body",priority=10,start_ms=0},
                new BodyCueView{action="point",layer="upper_body",priority=80,start_ms=200},
                new BodyCueView{action="small_nod",layer="additive",priority=20,start_ms=100}};
            var timeline=new PerformanceTimeline(performance,_=>1.5f);
            check(timeline.FaceAt(.3f)?.preset=="concerned","Later face cue must win only during its time window.");
            check(timeline.FaceAt(.8f)?.preset=="neutral","Earlier overlapping face cue must resume.");
            check(timeline.FaceAt(1.2f)==null,"Expired face cue must not persist.");
            check(timeline.BodyAt("upper_body",.1f)?.cue.action=="nod","Body cue cannot start early.");
            check(timeline.BodyAt("upper_body",.3f)?.cue.action=="point","Higher-priority body cue must win its layer.");
            check(timeline.BodyAt("additive",.3f)?.cue.action=="small_nod","Additive layer must coexist with upper body.");
            check(Math.Abs(timeline.Duration-1.7f)<.001f,"Timeline end must include final body clip duration.");
            check(!PerformanceTimeline.CanInterrupt("uninterruptible",0,100),"Uninterruptible speech cannot be preempted by a cue.");
            check(!PerformanceTimeline.CanInterrupt("allow_higher_priority",50,50),"Equal priority cannot interrupt.");
            check(PerformanceTimeline.CanInterrupt("allow_higher_priority",50,51),"Higher priority should interrupt.");
            check(PerformanceTimeline.CanInterrupt("allow_any",100,0),"Allow-any policy should allow lower priority.");
            PresentationClock.Reset();PresentationClock.Tick(.05f);float elapsed=PresentationClock.Elapsed;
            PresentationClock.Paused=true;for(int i=0;i<20;i++)PresentationClock.Tick(.05f);
            check(PresentationClock.Elapsed==elapsed&&PresentationClock.Delta==0,"Paused presentation clock must remain frozen.");
            PresentationClock.Paused=false;PresentationClock.Tick(5);
            check(PresentationClock.Delta<=.1001f,"Frame stalls cannot skip an entire cue.");
            PresentationClock.Reset();
            check(Rejects(p=>p.gaze.target="hidden_child"),"Unknown gaze target must be rejected.");
            check(Rejects(p=>p.gaze.mode="telepathy"),"Unknown gaze mode must be rejected.");
            check(Rejects(p=>p.face_cues=new[]{new FaceCueView{preset="sad",intensity=float.NaN,duration_ms=100}}),"NaN face intensity must be rejected.");
            check(Rejects(p=>p.body_cues=new[]{new BodyCueView{action="repair_joint",layer="full_body",priority=50}}),"Body cue cannot execute a physical world action.");
            check(PerformanceTimeline.FallbackFace(new EmotionView{primary="afraid",coarse="fear"})=="concerned","Actual v2 afraid must map to concern.");
            check(PerformanceTimeline.FallbackFace(new EmotionView{primary="guarded",coarse="neutral"})=="suspicious","Actual v2 guarded must map to suspicion.");
            check(PerformanceTimeline.FallbackFace(new EmotionView{primary="grateful",coarse="joy"})=="relieved_smile","Actual v2 grateful must map to relief.");
            check(PerformanceTimeline.FallbackFace(new EmotionView{coarse="sadness"})=="sad","Coarse sadness fallback must work.");
            check(Rejects(p=>p.emotion.coarse="positive"),"Non-v2 coarse emotion must be rejected.");
            check(PerformanceTimeline.ReadingSpeed("soft_restrained")<PerformanceTimeline.ReadingSpeed("excited"),"Voice style may change text cadence only.");
            return failures.ToArray();
        }
        public static PerformanceView Base()
        {
            return new PerformanceView{schema_version="1.0",npc_id="lin",turn_id="qa",
                dialogue=new DialogueView{text="先确认大家的情况。",language="zh-CN",voice_style="neutral"},
                emotion=new EmotionView{primary="afraid",coarse="fear",intensity=.6f},
                gaze=new GazeView{target="player_head",mode="direct"},interrupt_policy="allow_higher_priority"};
        }
        static bool Rejects(Action<PerformanceView> mutate)
        {
            var value=Base();mutate(value);
            try{new PerformanceTimeline(value,_=>1);return false;}
            catch(ArgumentException){return true;}
        }
    }
}
