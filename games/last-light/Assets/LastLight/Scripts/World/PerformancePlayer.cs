using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace LastLight
{
    [DefaultExecutionOrder(200)]
    public sealed class PerformancePlayer : MonoBehaviour
    {
        TrainWorld world;
        readonly Dictionary<string,PerformanceHandle> active=new Dictionary<string,PerformanceHandle>();
        readonly List<PerformanceHandle> waiting=new List<PerformanceHandle>();
        readonly List<PerformanceTrace> traces=new List<PerformanceTrace>();
        public IReadOnlyList<PerformanceTrace> Traces=>traces;
        public event Action<PerformanceHandle> Changed;
        public void Initialize(TrainWorld value){world=value;}

        public PerformanceHandle Begin(DialogueLine line)
        {
            var handle=new PerformanceHandle{lineId=line.id,npcId=line.npc_id};
            try
            {
                var performance=PerformanceTimeline.ForLine(line);
                if(!string.IsNullOrEmpty(performance.npc_id)&&performance.npc_id!=line.npc_id)
                    throw new ArgumentException("Performance actor does not match the dialogue line.");
                if(performance.dialogue!=null&&performance.dialogue.text!=line.text)
                    throw new ArgumentException("Performance text does not match the visible dialogue.");
                handle.timeline=new PerformanceTimeline(performance,action=>
                    world.TryActor(line.npc_id,out var actor)?actor.GestureDuration(action):1f);
                if(active.TryGetValue(handle.npcId,out var previous)&&!previous.Released&&previous.status!="interrupted"&&previous.status!="error")
                {
                    if(PerformanceTimeline.CanInterrupt(previous.timeline.Performance.interrupt_policy,
                        previous.timeline.Priority,handle.timeline.Priority))Interrupt(previous,"higher_priority",true);
                    else {waiting.Add(handle);Mark(handle,"queued","interrupt_policy");return handle;}
                }
                StartHandle(handle);
            }
            catch(Exception error)
            {
                handle.error=error.Message;handle.status="error";Mark(handle,"error",error.Message);
            }
            return handle;
        }
        void StartHandle(PerformanceHandle handle)
        {
            active[handle.npcId]=handle;handle.status="running";handle.elapsed=0;
            Mark(handle,"started","visual_timeline");
        }
        void LateUpdate()
        {
            if(world==null)return;
            foreach(var handle in active.Values.ToArray())
            {
                if(handle.Finished)
                {
                    if(handle.Successful&&!handle.Released&&!handle.offscreen&&world.TryActor(handle.npcId,out var holdingActor))
                        Sample(handle,holdingActor);
                    continue;
                }
                try
                {
                    if(!world.TryActor(handle.npcId,out var actor))
                    {
                        handle.offscreen=true;handle.visualsSkipped=true;
                        Complete(handle,"offscreen_not_rendered");continue;
                    }
                    Sample(handle,actor);
                    handle.elapsed+=PresentationClock.Delta;
                    if(handle.elapsed>=handle.timeline.Duration)Complete(handle,"timeline_finished");
                }
                catch(Exception error)
                {
                    handle.error=error.Message;handle.status="error";
                    if(world.TryActor(handle.npcId,out var actor))actor.ClearPerformance();
                    Mark(handle,"error",error.Message);
                }
            }
            foreach(var handle in waiting.ToArray())
                if(!active.TryGetValue(handle.npcId,out var previous)||previous.Released||previous.status=="interrupted"||previous.status=="error")
                {waiting.Remove(handle);StartHandle(handle);}
        }
        void Mark(PerformanceHandle handle,string kind,string detail)
        {
            traces.Add(new PerformanceTrace{line_id=handle.lineId,npc_id=handle.npcId,
                event_type=kind,detail=detail,at=PresentationClock.Elapsed});
            Changed?.Invoke(handle);
        }
        void Sample(PerformanceHandle handle,TrainActor actor)
        {
            actor.ClearPerformance();
            var timeline=handle.timeline;float elapsed=handle.elapsed;
            actor.SetMood(timeline.Performance.emotion);
            string secondary=timeline.Performance.emotion?.secondary;
            if(!string.IsNullOrEmpty(secondary)&&handle.marks.Add("secondary"))
                Mark(handle,"secondary_preserved",secondary+":metadata_only");
            var face=timeline.FaceAt(elapsed);
            if(face!=null)
            {
                float start=face.start_ms/1000f,end=(face.start_ms+face.duration_ms)/1000f;
                float fade=Mathf.Min(Mathf.Clamp01((elapsed-start)/.12f),Mathf.Clamp01((end-elapsed)/.12f));
                actor.SetFace(face.preset,face.intensity*fade);
                string key="face:"+Array.IndexOf(timeline.FacesInOrder,face);
                if(handle.marks.Add(key))Mark(handle,"face_sampled",key+":"+face.preset);
            }
            else
                actor.SetFace(PerformanceTimeline.FallbackFace(timeline.Performance.emotion),
                    Mathf.Clamp01(timeline.Performance.emotion?.intensity??.5f));
            foreach(string layer in PerformanceTimeline.Layers)
            {
                var window=timeline.BodyAt(layer,elapsed);if(window==null)continue;
                string key="body:"+window.index;
                if(!actor.CanGesture(window.cue.action,layer))
                {
                    handle.visualsSkipped=true;
                    if(handle.marks.Add(key+":blocked"))Mark(handle,"cue_blocked",key+":occupied_or_missing");
                    continue;
                }
                actor.SampleGesture(window.cue.action,layer,elapsed-window.start);
                if(handle.marks.Add(key))Mark(handle,"body_sampled",key+":"+window.cue.action+":"+layer);
            }
            var gaze=timeline.Performance.gaze??new GazeView{target="player_head",mode="soft_focus"};
            Vector3 position;bool visible=world.ResolveGaze(handle.npcId,gaze.target,out position);
            if(!visible)visible=world.ResolveGaze(handle.npcId,"ground",out position);
            actor.SetGaze(visible?(Vector3?)position:null,gaze.mode);
            if(handle.marks.Add("gaze"))Mark(handle,"gaze_bound",gaze.target+":"+gaze.mode+(visible?"":":unavailable"));
        }
        void Complete(PerformanceHandle handle,string reason)
        {
            handle.status="completed";
            foreach(var body in handle.timeline.Bodies)
            {
                string key="body:"+body.index;
                if(!handle.marks.Contains(key)&&!handle.marks.Contains(key+":blocked"))
                    Mark(handle,"cue_superseded",key+":priority_or_explicit_skip");
            }
            Mark(handle,"completed",reason);
        }
        public void Skip(PerformanceHandle handle)
        {
            if(handle==null||handle.Finished)return;
            waiting.Remove(handle);handle.visualsSkipped=true;
            handle.elapsed=handle.timeline.Duration;Complete(handle,"player_skipped_visuals");
        }
        public bool Interrupt(PerformanceHandle handle,string reason,bool force=true,int priority=100)
        {
            if(handle==null||handle.Released||handle.status=="interrupted"||handle.status=="error")return false;
            if(!force&&!PerformanceTimeline.CanInterrupt(handle.timeline.Performance.interrupt_policy,
                handle.timeline.Priority,priority))return false;
            waiting.Remove(handle);handle.status="interrupted";
            if(world.TryActor(handle.npcId,out var actor))actor.ClearPerformance();
            Mark(handle,"interrupted",reason);return true;
        }
        public void Release(PerformanceHandle handle)
        {
            if(handle==null)return;handle.Released=true;
            if(active.TryGetValue(handle.npcId,out var current)&&current==handle&&world.TryActor(handle.npcId,out var actor))
                actor.ClearPerformance();
        }
        public void StopAll(string reason)
        {
            foreach(var handle in active.Values.Concat(waiting).Distinct().ToArray())Interrupt(handle,reason);
            waiting.Clear();active.Clear();
        }
        public bool AnyRunning=>active.Values.Any(h=>!h.Finished)||waiting.Count>0;
    }
}
