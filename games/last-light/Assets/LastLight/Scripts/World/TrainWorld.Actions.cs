using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace LastLight
{
    public sealed partial class TrainWorld
    {
        ExecutionView preparedExecution;
        public string PresentationStage { get; private set; }="idle";
        public int PhysicalPresentationCommits { get; private set; }
        readonly HashSet<string> presentedCommits=new HashSet<string>();
        public IEnumerator Animate(ExecutionView execution)=>Prepare(execution); // Legacy QA entry: preparation only.
        public IEnumerator Prepare(ExecutionView execution)
        {
            if(execution==null)yield break;
            preparedExecution=execution;animating=true;skipAnimation=false;PresentationStage="approaching";
            playerPath.Clear();pendingTarget="";
            var workers=new List<TrainActor>();
            foreach(var step in execution.steps??Array.Empty<PlanStep>())
            {
                if(step.presentation==null)throw new InvalidOperationException("Missing explicit action presentation: "+step.action_id);
                var ids=new[]{step.actor_id}.Concat(step.helpers??Array.Empty<string>()).Distinct().ToArray();
                bool localTarget=TargetPosition(step.visible_target_id??"",out var target);
                if(!localTarget&&TargetPosition(step.source_id??"",out var source))target=source;
                if(!localTarget&&string.IsNullOrEmpty(step.source_id))continue; // Offscreen work is never staged here.
                int slot=0;
                foreach(var id in ids)
                {
                    if(!actors.TryGetValue(id,out var actor))continue;
                    actor.StopWork();actor.Destination=(step.target_id=="blocked_door"?new Vector3(-6.1f,0,-.3f):Approach(target))+Vector3.right*(slot++*.45f);
                    workers.Add(actor);
                }
            }
            float elapsed=0;
            while(!skipAnimation&&workers.Any(a=>!a.Arrived))
            {
                elapsed+=PresentationClock.Delta;
                if(elapsed>30)throw new InvalidOperationException("A character could not reach the reserved work position.");
                yield return null;
            }
            PresentationStage="preparing";
            foreach(var step in execution.steps??Array.Empty<PlanStep>())
            {
                foreach(var id in new[]{step.actor_id}.Concat(step.helpers??Array.Empty<string>()).Distinct())
                    if(actors.TryGetValue(id,out var actor))
                    {
                        actor.PlayWork(step.presentation.preparation_clip,true);
                        if(TargetPosition(step.visible_target_id??step.target_id,out var target))actor.SetGaze(target+Vector3.up*.7f,"direct");
                    }
                if(step.presentation.visual_kind=="handoff"&&actors.TryGetValue(step.source_id??"",out var giver))giver.PlayWork("offer_item",true);
            }
            yield return WaitPresentation(1.2f);
            PresentationStage="awaiting_commit";
            // The caller now submits /complete. No item ownership or successful device state was shown.
        }
        IEnumerator WaitPresentation(float seconds)
        {float elapsed=0;while(!skipAnimation&&elapsed<seconds){elapsed+=PresentationClock.Delta;yield return null;}}
        public IEnumerator Resolve(ExecutionView execution,GameView before,GameView after)
        {
            if(execution==null||after==null)yield break;
            if(!presentedCommits.Add(after.session_id+":"+execution.id)){Apply(after);yield break;}
            PhysicalPresentationCommits++;resolving=true;PresentationStage="result";
            try
            {
                var resultingPlan=(after.plans??Array.Empty<PlanView>()).FirstOrDefault(p=>p.id==execution.plan_id);
                var steps=execution.steps??Array.Empty<PlanStep>();
                var completed=steps.Where(s=>resultingPlan?.steps?.Any(r=>r.id==s.id&&r.status=="completed")==true).ToArray();
                if(after.room_id!=before.room_id)
                {
                    foreach(var step in completed.Where(s=>s.presentation.visual_kind=="escort"||s.presentation.visual_kind=="gather"||s.action_id=="escort_mother"))
                        yield return TransferResult(step,before,after);
                    if(!completed.Any(s=>s.presentation.visual_kind=="escort"||s.presentation.visual_kind=="gather"||s.action_id=="escort_mother")&&Actor("player")!=null)
                    {
                        var traveller=Actor("player");traveller.StopWork();traveller.Destination=ExitTowards(after.room_id);
                        float time=0;while(!skipAnimation&&!traveller.Arrived){time+=PresentationClock.Delta;if(time>30)throw new InvalidOperationException("Could not reach the observed departure portal");yield return null;}
                    }
                    Apply(after); // Enter only the region actually reached by this committed action.
                    visualConnections=before;
                    foreach(var step in completed.Where(s=>s.presentation.visual_kind=="connect"))
                        foreach(string id in step.item_ids??Array.Empty<string>())
                            if(id=="backup"&&Actor(step.actor_id)!=null)items.Bind(id,Actor(step.actor_id).Socket("hand_r"));
                }
                foreach(var step in steps)
                {
                    bool done=completed.Contains(step);
                    string clip=done?step.presentation.result_clip:step.presentation.failed_clip;
                    foreach(var id in new[]{step.actor_id}.Concat(step.helpers??Array.Empty<string>()).Distinct())
                        if(actors.TryGetValue(id,out var actor))actor.PlayWork(clip);
                }
                // Handoffs share one model and bind only after the authoritative response.
                foreach(var step in completed)
                {
                    string kind=step.presentation.visual_kind;
                    if(kind=="handoff"||kind=="pickup"||kind=="connect"||kind=="disconnect")
                        yield return ItemResult(step,before,after);
                    else if(kind=="escort"||kind=="evacuate"||kind=="gather"||kind=="move"||kind=="stretcher_transfer"||step.action_id=="escort_mother")
                    {
                        if(after.room_id==before.room_id)yield return TransferResult(step,before,after);
                        else
                        {
                            if(step.action_id=="reunite_child"&&Actor("zhou")!=null&&Actor("xiaoman")!=null)Actor("zhou").PlayWork("reunion");
                            yield return WaitPresentation(.7f);
                        }
                    }
                    else if(kind=="door"||kind=="cart"||kind=="repair"||kind=="retest"||kind=="isolate"||kind=="power_restore"||kind=="stretcher"||step.action_id=="inspect_joint")
                        yield return DeviceResult(step,after);
                    else
                    {
                        PlayCue(kind=="repair"||kind=="retest"?"tools":kind=="door"?"door":"click");
                        yield return WaitPresentation(PresentationAssets.Required.Clip(step.presentation.result_clip).duration);
                    }
                }
                if(completed.Length==0)yield return WaitPresentation(.6f);
            }
            finally
            {
                resolving=false;animating=false;preparedExecution=null;PresentationStage="idle";
                foreach(var actor in actors.Values){actor.ExternalMovement=false;actor.StopWork();}
                items.StowTools();
                Apply(after);items.Validate();
            }
        }
        IEnumerator ItemResult(PlanStep step,GameView before,GameView after)
        {
            string kind=step.presentation.visual_kind;
            string itemId=(step.presentation.resource_ids??Array.Empty<string>()).FirstOrDefault(i=>
                (before.inventory??Array.Empty<ItemView>()).Any(b=>b.id==i))??"";
            var item=items.Get(itemId);
            var changed=(after.inventory??Array.Empty<ItemView>()).FirstOrDefault(i=>i.id==itemId);
            if(item==null||changed==null){yield return WaitPresentation(.3f);yield break;}
            var giver=Actor(step.source_id);var recipient=Actor(changed.holder_id);
            if(kind=="handoff")
            {
                giver?.PlayWork("offer_item");recipient?.PlayWork("receive_item");
                var contact=item.transform.position;
                if(giver!=null&&recipient!=null)contact=(giver.transform.position+recipient.transform.position)*.5f+Vector3.up*1.05f;
                giver?.SetHandTarget(false,contact);recipient?.SetHandTarget(true,contact);
                Vector3 start=item.transform.position;float t=0;
                items.Move(itemId,start);
                while(!skipAnimation&&t<.55f){t+=PresentationClock.Delta;items.Move(itemId,Vector3.Lerp(start,contact,Mathf.Clamp01(t/.55f)));yield return null;}
                items.Move(itemId,contact);yield return WaitPresentation(.22f);
                if(recipient!=null){items.Bind(itemId,recipient.Socket("hand_l"));recipient.SetHolding("hand_l",true);}
                giver?.SetHandTarget(false,null);yield return WaitPresentation(.45f);recipient?.SetHandTarget(true,null);
            }
            else
            {
                var worker=Actor(step.actor_id);var start=item.transform.position;
                Vector3 end=start;
                if(kind=="pickup"||kind=="disconnect")
                {if(worker!=null)end=worker.Socket("hand_r").position;}
                else
                {
                    string target=changed.connected_to=="medical"?"oxygen":changed.connected_to;
                    if(TargetPosition(target,out var point))end=point+new Vector3(.36f,.05f,0);
                }
                worker?.SetHandTarget(false,end+Vector3.up*.15f);
                float t=0;
                while(!skipAnimation&&t<.9f){t+=PresentationClock.Delta;items.Move(itemId,Vector3.Lerp(start,end,Mathf.SmoothStep(0,1,t/.9f)));yield return null;}
                items.Move(itemId,end);
                if((kind=="pickup"||kind=="disconnect")&&worker!=null)items.Bind(itemId,worker.Socket("hand_r"));
                // Connections become visible only in this confirmed result tail.
                if(kind=="connect"||kind=="disconnect"){visualConnections=after;items.UpdateCable(after,Object);}
                PlayCue("click");yield return WaitPresentation(.25f);worker?.SetHandTarget(false,null);
            }
        }
        IEnumerator DeviceResult(PlanStep step,GameView after)
        {
            var target=Object(step.visible_target_id??step.target_id);var worker=Actor(step.actor_id);
            string kind=step.presentation.visual_kind;
            if(kind=="repair"||kind=="retest"||step.action_id=="inspect_joint")items.PresentTool(kind=="repair"?"driver":"meter",worker);
            Transform moving=null;Vector3 start=Vector3.zero,end=Vector3.zero;Quaternion oldRotation=Quaternion.identity,newRotation=Quaternion.identity;
            if(target!=null)
            {
                if(kind=="door")moving=target.GetComponentsInChildren<Transform>().FirstOrDefault(t=>t.name=="DoorLeaf");
                if(kind=="cart")moving=target.transform.Find("DisplacedTrolley");
                if(moving!=null)
                {
                    start=moving.localPosition;oldRotation=moving.localRotation;
                    end=kind=="door"?new Vector3(1.03f,0,0):new Vector3(1.35f,0,.4f);
                    newRotation=kind=="cart"?Quaternion.Euler(0,75,0):oldRotation;
                }
                var contact=(step.presentation.socket_ids??Array.Empty<string>()).Select(id=>PresentationSockets.Find(target,id)).FirstOrDefault(t=>t!=null);
                worker?.SetHandTarget(false,contact!=null?contact.position:target.transform.position+new Vector3(.2f,.93f,-.15f));
            }
            float duration=PresentationAssets.Required.Clip(step.presentation.result_clip).duration,time=0;
            while(!skipAnimation&&time<duration)
            {
                time+=PresentationClock.Delta;float fraction=Mathf.SmoothStep(0,1,time/duration);
                if(moving!=null){moving.localPosition=Vector3.Lerp(start,end,fraction);moving.localRotation=Quaternion.Slerp(oldRotation,newRotation,fraction);}
                if(step.action_id=="prepare_stretcher"&&items.Get("stretcher")!=null)
                    items.Get("stretcher").transform.localScale=Vector3.Lerp(new Vector3(.75f,.45f,1),Vector3.one,fraction);
                yield return null;
            }
            if(moving!=null){moving.localPosition=end;moving.localRotation=newRotation;}
            var result=(after.objects??Array.Empty<ObjectView>()).FirstOrDefault(o=>o.id==step.target_id);
            if(target!=null&&result!=null){WorldGeometry.ApplyPropState(target,result.id,result.state);objectStates[result.id]=result.state;}
            worker?.SetHandTarget(false,null);items.StowTools();PlayCue(kind=="door"?"door":"tools");
        }
        IEnumerator TransferResult(PlanStep step,GameView before,GameView after)
        {
            var ids=(step.participant_ids??Array.Empty<string>()).Distinct().ToArray();
            var travelling=new List<TrainActor>();var starts=new List<Vector3>();var ends=new List<Vector3>();
            foreach(string id in ids)
            {
                var old=(before.actors??Array.Empty<ActorView>()).FirstOrDefault(a=>a.id==id);
                var next=(after.actors??Array.Empty<ActorView>()).FirstOrDefault(a=>a.id==id);
                if(old==null||!actors.TryGetValue(id,out var actor))continue;
                Vector3 end;
                if(next!=null&&next.room_id==room)end=Point(next.x,next.z);
                else
                {
                    string destination=new[]{"escort_mother","escort_child","escort_passengers","move_to_refuge","finish_evacuation"}.Contains(step.action_id)?"tunnel":"cabin07";
                    end=ExitTowards(destination)+Vector3.right*travelling.Count*.18f;
                }
                if(Vector3.Distance(actor.transform.position,end)<.04f)continue;
                travelling.Add(actor);starts.Add(actor.transform.position);ends.Add(end);
                actor.ExternalMovement=true;actor.Destination=end;actor.Pose=id=="mother"&&step.action_id=="escort_mother"?"carried_litter":"assisted_walk";
                actor.PlayWork(actor.Pose=="carried_litter"?"carried_litter":id=="mother"?"escort_walk":step.action_id=="escort_mother"?"lift_stretcher":"escort_walk");
            }
            var mother=travelling.FirstOrDefault(a=>a.Id=="mother");
            var litter=items.Get("stretcher");
            if(mother!=null)
            {
                var medical=items.Get("medical");if(medical!=null){medical.transform.SetParent(mother.transform,true);medical.transform.localPosition=new Vector3(.4f,.55f,.2f);}
                var backup=(before.inventory??Array.Empty<ItemView>()).FirstOrDefault(i=>i.id=="backup");
                if(backup?.connected_to=="medical"&&items.Get("backup")!=null)
                {var supply=items.Get("backup");supply.transform.SetParent(mother.transform,true);supply.transform.localPosition=new Vector3(.6f,.55f,.2f);}
                if(step.action_id=="escort_mother"&&litter!=null)
                {litter.transform.SetParent(mother.transform,false);litter.transform.localPosition=Vector3.up*.75f;litter.transform.localScale=Vector3.one;}
            }
            // A litter is one formation, with actual accepted helpers on its two ends.
            if(mother!=null&&step.action_id=="escort_mother"&&litter!=null)
            {
                int patientIndex=travelling.IndexOf(mother);int helperIndex=0;
                Vector3 direction=(ends[patientIndex]-starts[patientIndex]).normalized;
                var orientation=direction.sqrMagnitude>.001f?Quaternion.LookRotation(direction,Vector3.up):Quaternion.identity;
                for(int i=0;i<travelling.Count;i++)
                {
                    if(travelling[i]==mother)continue;
                    float endOffset=helperIndex++%2==0?1.05f:-1.05f;
                    var offset=orientation*new Vector3(0,0,endOffset);
                    starts[i]=starts[patientIndex]+offset;ends[i]=ends[patientIndex]+offset;
                    travelling[i].transform.position=starts[i];
                    travelling[i].SetHandTarget(true,mother.transform.position+orientation*new Vector3(-.35f,.8f,endOffset*.85f));
                    travelling[i].SetHandTarget(false,mother.transform.position+orientation*new Vector3(.35f,.8f,endOffset*.85f));
                }
            }
            float distance=starts.Zip(ends,(a,b)=>Vector3.Distance(a,b)).DefaultIfEmpty(0).Max();float progress=0;
            while(!skipAnimation&&progress<1)
            {
                progress=Mathf.Min(1,progress+PresentationClock.Delta*1.2f/Mathf.Max(.01f,distance));
                for(int i=0;i<travelling.Count;i++)
                {
                    var actor=travelling[i];actor.transform.position=Vector3.Lerp(starts[i],ends[i],progress);
                    var direction=ends[i]-starts[i];if(direction.sqrMagnitude>.001f)actor.transform.rotation=Quaternion.LookRotation(direction.normalized,Vector3.up);
                }
                if(mother!=null&&step.action_id=="escort_mother"&&litter!=null)
                {
                    int helperIndex=0;
                    foreach(var helper in travelling.Where(a=>a!=mother))
                    {
                        float endOffset=helperIndex++%2==0?.9f:-.9f;
                        helper.SetHandTarget(true,litter.transform.TransformPoint(new Vector3(-.35f,.05f,endOffset)));
                        helper.SetHandTarget(false,litter.transform.TransformPoint(new Vector3(.35f,.05f,endOffset)));
                    }
                }
                items.UpdateCable(before,Object);yield return null;
            }
            for(int i=0;i<travelling.Count;i++){travelling[i].transform.position=ends[i];travelling[i].ExternalMovement=false;}
            if(step.action_id=="reunite_child"&&Actor("zhou")!=null&&Actor("xiaoman")!=null&&
                (after.actors??Array.Empty<ActorView>()).Any(a=>a.id=="zhou"))
            {Actor("zhou").PlayWork("reunion");yield return WaitPresentation(1.2f);}
        }
        public void ValidatePresentation(){items?.Validate();}
        public string[] ValidatePresentation(GameView expected)
        {
            var errors=new List<string>();
            try{items?.Validate();}catch(Exception e){errors.Add(e.Message);}
            var visible=new HashSet<string>((expected.actors??Array.Empty<ActorView>()).Where(a=>a.room_id==expected.room_id).Select(a=>a.id));
            foreach(var id in actors.Keys)if(!visible.Contains(id))errors.Add("Unobserved actor rendered: "+id);
            foreach(var id in visible)if(!actors.ContainsKey(id))errors.Add("Visible actor missing: "+id);
            foreach(var item in expected.inventory??Array.Empty<ItemView>())
            {
                bool shouldShow=item.state!="consumed"&&item.room_id==expected.room_id;
                var go=items?.Get(item.id);if(shouldShow&&(go==null||!go.activeInHierarchy))errors.Add("Visible item missing: "+item.id);
                if(!shouldShow&&go!=null&&go.activeInHierarchy)errors.Add("Hidden item shown: "+item.id);
            }
            foreach(var actor in actors.Values)if(string.IsNullOrEmpty(actor.ActiveClip))errors.Add("Missing active clip: "+actor.Id);
            return errors.ToArray();
        }
    }
}
