using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace LastLight
{
    [Serializable] public sealed class PlaybackEventLog
    {
        public string line_id,event_id,event_type,error;
        public bool visuals_skipped,ok;
        public float at;
    }
    public sealed partial class LastLightApp
    {
        PerformanceHandle playingPerformance;
        string currentSpeaker="",playingLineId="",playingJobId="";
        bool playingHasStarted;
        Button skipPerformanceButton;
        readonly Dictionary<string,PerformanceEventRequest> playbackRequests=new Dictionary<string,PerformanceEventRequest>();
        readonly List<PlaybackEventLog> playbackEvents=new List<PlaybackEventLog>();
        public IReadOnlyList<PlaybackEventLog> PlaybackEvents=>playbackEvents;
        public PerformancePlayer Performance=>performancePlayer;
        public PerformanceHandle CurrentPerformanceHandle=>playingPerformance;
        public string CurrentSpeaker=>currentSpeaker;
        public GameView CurrentView=>view;
        public bool PresentationBusy=>animating||HasActiveTalk;
        public void CaptureOpenView(GameView snapshot)
        {
            if(!qaCapture)throw new InvalidOperationException("Capture mode is not enabled.");
            OpenSession(snapshot);
        }
        public void CaptureSetPaused(bool paused){if(qaCapture)qaPauseRequested=paused;}
        public void CaptureCloseOverlay(){if(qaCapture)CloseModal();}
        public void CaptureAdvanceLine()
        {
            if(!qaCapture)return;
            if(revealingText)RevealNow();
            else if(awaitingAdvance)advanceRequested=true;
        }
        public void CaptureBeginLine(DialogueLine line)
        {
            if(!qaCapture)throw new InvalidOperationException("Capture mode is not enabled.");
            ReleaseLocalTalk();queuedLineIds.Clear();pendingLines.Clear();
            activeJob=new TalkJob{id="capture-"+line.id,status="completed",source="recorded"};
            queuedLineIds.Add(line.id);pendingLines.Enqueue(line);
            deliveryRoutine=StartCoroutine(DeliverLines(sessionGeneration,talkGeneration,activeJob.id));
        }
        public void CaptureSkipVisuals(){if(qaCapture)SkipCurrentPerformance();}
        public void CaptureInterrupt(){if(qaCapture)CancelTalk();}

        void RefreshSpeakerPortrait()
        {
            string id=string.IsNullOrEmpty(currentSpeaker)?selectedNpc:currentSpeaker;
            var actor=view?.actors?.FirstOrDefault(a=>a.id==id);
            bool speaking=!string.IsNullOrEmpty(currentSpeaker);
            targetText.text=string.IsNullOrEmpty(id)?"观察与调查":
                ActorName(id)+(speaking?" · 正在说话":actor==null?"": " · "+actor.role)+(actor==null?" · 不在附近":"");
            targetText.color=string.IsNullOrEmpty(id)?UiFactory.Amber:UiFactory.ActorColor(id);
            portrait.texture=string.IsNullOrEmpty(id)||(actor==null&&!IsNpc(id))?null:world.Portrait(id);
            portrait.gameObject.SetActive(portrait.texture!=null);
        }
        void SkipCurrentPerformance()
        {
            if(playingPerformance==null||playingPerformance.Finished)return;
            performancePlayer.Skip(playingPerformance);
            skipPerformanceButton.gameObject.SetActive(false);
        }
        static string PlaybackEventId(string session,string job,string line,string kind)
        {
            using(var hash=SHA256.Create())
                return "ll_"+BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(session+"|"+job+"|"+line+"|"+kind))).Replace("-","").ToLowerInvariant();
        }
        void SendPlaybackEvent(string job,string line,string kind,bool skipped,Action<ApiResponse> done)
        {
            string key=sessionId+"|"+job+"|"+line+"|"+kind;
            if(!playbackRequests.TryGetValue(key,out var request))
            {
                request=new PerformanceEventRequest{line_id=line,event_id=PlaybackEventId(sessionId,job,line,kind),
                    event_type=kind,visuals_skipped=skipped};playbackRequests[key]=request;
            }
            Action<ApiResponse> receive=response=>
            {
                playbackEvents.Add(new PlaybackEventLog{line_id=line,event_id=request.event_id,event_type=kind,
                    visuals_skipped=request.visuals_skipped,ok=response.ok,error=response.error,at=PresentationClock.Elapsed});
                done?.Invoke(response);
            };
            if(qaCapture)receive(new ApiResponse{ok=true});
            else client.Post(SessionPath("talk/"+Uri.EscapeDataString(job)+"/performance-events"),request,receive);
        }
    }
}
