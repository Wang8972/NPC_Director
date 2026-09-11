using System;
using System.Collections;
using System.Linq;
using UnityEngine;

namespace LastLight.QA
{
    public sealed partial class PlayerCapture
    {
        IEnumerator RunLineFixture(PerformanceFixture fixture,bool testPause,bool interrupt,bool skip)
        {
            string name=string.IsNullOrEmpty(fixture.id)?fixture.line.id:fixture.id;performanceCount++;
            Show(fixture.before);app.CaptureCloseOverlay();yield return null;
            int tick=fixture.before.tick,revision=fixture.before.revision;
            bool hasActor=world.TryActor(fixture.line.npc_id,out var actor);
            Vector3 position=hasActor?actor.transform.position:Vector3.zero;
            bool running=true;var recording=StartCoroutine(CaptureFrames(name,()=>running));
            int oldEventCount=app.PlaybackEvents.Count;
            app.CaptureBeginLine(fixture.line);
            float deadline=Time.realtimeSinceStartup+15;
            if(fixture.line.delivered||fixture.line.delivery_status=="delivered")
            {
                while(app.PresentationBusy&&Time.realtimeSinceStartup<deadline)yield return null;
                running=false;StopCoroutine(recording);
                Check(app.PlaybackEvents.Count==oldEventCount,name+":legacy_history_not_redelivered");
                Validate(fixture.before,name+":legacy_entities");yield return Shot(name+"-end");yield break;
            }
            while(app.CurrentPerformanceHandle==null&&app.PresentationBusy&&Time.realtimeSinceStartup<deadline)yield return null;
            var handle=app.CurrentPerformanceHandle;
            Check(handle!=null,name+":timeline_created");
            if(handle!=null)
            {
                while(handle.elapsed<.25f&&!handle.Finished&&Time.realtimeSinceStartup<deadline)yield return null;
                yield return new WaitForEndOfFrame();
                Check(app.CurrentSpeaker==fixture.line.npc_id,name+":current_speaker");
                if(testPause)
                {
                    app.CaptureSetPaused(true);yield return null;
                    float before=handle.elapsed,clock=PresentationClock.Elapsed;
                    yield return new WaitForSecondsRealtime(.35f);yield return new WaitForEndOfFrame();
                    Check(handle.elapsed==before&&PresentationClock.Elapsed==clock,name+":paused_clock_and_cues");
                    app.CaptureSetPaused(false);
                }
                var first=fixture.line.performance?.face_cues?.FirstOrDefault();
                if(first!=null&&hasActor)
                {
                    bool applied=actor.Visual.GetComponentsInChildren<SkinnedMeshRenderer>().Any(renderer=>
                    {
                        if(renderer.sharedMesh==null)return false;
                        int shape=renderer.sharedMesh.GetBlendShapeIndex(first.preset);
                        return shape>=0&&renderer.GetBlendShapeWeight(shape)>1;
                    });
                    Check(applied,name+":real_blendshape_weight",first.preset);
                }
                if(interrupt)app.CaptureInterrupt();
                else if(skip)app.CaptureSkipVisuals();
            }
            while(app.PresentationBusy&&Time.realtimeSinceStartup<deadline)
            {app.CaptureAdvanceLine();yield return null;}
            running=false;StopCoroutine(recording);
            Check(!app.PresentationBusy,name+":playback_finished");
            if(app.PresentationBusy){app.CaptureInterrupt();app.CaptureCloseOverlay();}
            var events=app.PlaybackEvents.Where(e=>e.line_id==fixture.line.id&&e.ok).ToArray();
            var kinds=events.Select(e=>e.event_type).Distinct().ToArray();
            if(interrupt)
                Check(kinds.Contains("started")&&kinds.Contains("interrupted")&&!kinds.Contains("completed"),name+":interrupted_not_delivered");
            else
                Check(kinds.SequenceEqual(new[]{"ack","started","completed"}),name+":delivery_order",string.Join(",",kinds));
            if(skip)Check(events.Any(e=>e.event_type=="completed"&&e.visuals_skipped),name+":skip_recorded");
            foreach(var group in events.GroupBy(e=>e.event_type))
                Check(group.Select(e=>e.event_id).Distinct().Count()==1,name+":stable_event_id",group.Key);
            Check(app.CurrentView.tick==tick&&app.CurrentView.revision==revision,name+":performance_did_not_mutate_world");
            if(hasActor)Check(Vector3.Distance(position,actor.transform.position)<.001f,name+":no_actor_root_motion");
            Validate(fixture.before,name+":entities");yield return Shot(name+"-end");
        }
    }
}
