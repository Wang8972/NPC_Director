using System;
using System.Collections;
using TMPro;
using UnityEngine;

namespace LastLight
{
    public sealed partial class LastLightApp
    {
        bool DialogueCurrent(int generation,int conversation)=>generation==sessionGeneration&&conversation==talkGeneration;
        IEnumerator RequirePlaybackEvent(string job,string line,string kind,bool skipped,int generation,int conversation,
            Action<ApiResponse> done,ApiResponse first=null)
        {
            ApiResponse response=first;
            while(DialogueCurrent(generation,conversation))
            {
                if(response==null)
                {
                    SendPlaybackEvent(job,line,kind,skipped,r=>response=r);
                    while(response==null&&DialogueCurrent(generation,conversation))yield return null;
                }
                if(!DialogueCurrent(generation,conversation))yield break;
                if(response.ok){done(response);yield break;}
                bool decided=false,retry=false;
                var body=OpenModal("对话进度尚未确认",750,470);
                UiFactory.FlowText(body,response.error??"本机服务没有返回确认。",25);
                UiFactory.FlowText(body,"重试不会重复交付这句话。也可以停止此次交谈。",23,UiFactory.Muted);
                UiFactory.Button("Retry playback event",body,"重试",()=>{retry=true;decided=true;CloseModal();},true);
                UiFactory.Button("Stop playback",body,"停止交谈",()=>{decided=true;CloseModal();});
                while(!decided&&modalOpen&&DialogueCurrent(generation,conversation))yield return null;
                if(!DialogueCurrent(generation,conversation))yield break;
                if(!retry){done(response);yield break;}
                response=null;
            }
        }
        IEnumerator PresentLine(DialogueLine line,int generation,int conversation,string job,Action<bool> done)
        {
            playingLineId=line.id;playingJobId=job;playingHasStarted=false;
            ApiResponse accepted=null;
            yield return RequirePlaybackEvent(job,line.id,"ack",false,generation,conversation,r=>accepted=r);
            if(!DialogueCurrent(generation,conversation))yield break;
            if(accepted==null||!accepted.ok){done(false);yield break;}
            while((modalOpen||titleOpen||introPlaying)&&DialogueCurrent(generation,conversation))yield return null;
            if(!DialogueCurrent(generation,conversation))yield break;
            playingPerformance=performancePlayer.Begin(line);
            if(playingPerformance.status=="error")
            {
                SendPlaybackEvent(job,line.id,"error",false,_=>{});
                ShowError("无法播放角色演出："+playingPerformance.error);done(false);yield break;
            }
            while(!playingPerformance.Started&&DialogueCurrent(generation,conversation))yield return null;
            if(!DialogueCurrent(generation,conversation))yield break;
            currentSpeaker=line.npc_id;RefreshSpeakerPortrait();
            world.Focus(line.npc_id);
            revealingBody=AddConversationLine(line,true);revealingBody.ForceMeshUpdate();
            int characters=revealingBody.textInfo.characterCount;
            revealingBody.maxVisibleCharacters=Math.Min(1,characters);
            revealingText=true;awaitingAdvance=false;advanceRequested=false;
            nextTextButton.gameObject.SetActive(true);UiFactory.SetLabel(nextTextButton,"显示全文");
            skipPerformanceButton.gameObject.SetActive(!playingPerformance.Finished);
            dialogueStatus.text=(line.source=="rehearsal"?"预设演练 · ":"")+line.speaker+"正在说话";
            yield return new WaitForEndOfFrame();
            playingHasStarted=true;ApiResponse started=null;
            SendPlaybackEvent(job,line.id,"started",false,r=>started=r);
            if(reducedMotion)SkipCurrentPerformance();
            float count=1;
            while(revealingText&&count<characters&&DialogueCurrent(generation,conversation))
            {
                if(!PresentationClock.Paused)
                    count+=instantText?characters+1:PresentationClock.Delta*
                        PerformanceTimeline.ReadingSpeed(playingPerformance.timeline.Performance.dialogue?.voice_style);
                revealingBody.maxVisibleCharacters=Mathf.Min(characters,(int)count);
                Canvas.ForceUpdateCanvases();dialogueScroll.verticalNormalizedPosition=0;
                yield return null;
            }
            if(!DialogueCurrent(generation,conversation))yield break;
            revealingText=false;revealingBody.maxVisibleCharacters=int.MaxValue;
            awaitingAdvance=true;UiFactory.SetLabel(nextTextButton,"继续");
            dialogueStatus.text="读完后点击「继续」；可以单独略过动作";
            while((!advanceRequested||!playingPerformance.Finished||PresentationClock.Paused)&&DialogueCurrent(generation,conversation))
            {
                skipPerformanceButton.gameObject.SetActive(!playingPerformance.Finished);
                if(advanceRequested&&!playingPerformance.Finished)dialogueStatus.text="正在完成角色演出…可点击「略过动作」";
                yield return null;
            }
            if(!DialogueCurrent(generation,conversation))yield break;
            if(!playingPerformance.Successful)
            {
                SendPlaybackEvent(job,line.id,playingPerformance.status=="error"?"error":"interrupted",
                    playingPerformance.visualsSkipped,_=>{});
                SetStatus("这段演出没有完成，尚未形成新的安排。",10);done(false);yield break;
            }
            while(started==null&&DialogueCurrent(generation,conversation))yield return null;
            if(!DialogueCurrent(generation,conversation))yield break;
            ApiResponse startedReceipt=null;
            yield return RequirePlaybackEvent(job,line.id,"started",false,generation,conversation,r=>startedReceipt=r,started);
            if(!DialogueCurrent(generation,conversation))yield break;
            if(startedReceipt==null||!startedReceipt.ok){done(false);yield break;}
            awaitingAdvance=false;nextTextButton.gameObject.SetActive(false);skipPerformanceButton.gameObject.SetActive(false);
            ApiResponse completed=null;
            yield return RequirePlaybackEvent(job,line.id,"completed",playingPerformance.visualsSkipped,
                generation,conversation,r=>completed=r);
            if(!DialogueCurrent(generation,conversation))yield break;
            if(completed==null||!completed.ok){done(false);yield break;}
            acknowledgedLineIds.Add(line.id);
            if(completed.view!=null)ApplyView(completed.view);
            if(completed.job!=null)AcceptJob(completed.job);
            ClearCurrentPerformance();done(true);
        }
        void ClearCurrentPerformance()
        {
            if(playingPerformance!=null&&!playingPerformance.Finished)performancePlayer.Interrupt(playingPerformance,"cancelled");
            if(playingPerformance!=null)performancePlayer.Release(playingPerformance);
            playingPerformance=null;playingLineId="";playingJobId="";playingHasStarted=false;currentSpeaker="";
            if(skipPerformanceButton!=null)skipPerformanceButton.gameObject.SetActive(false);
            if(view!=null)RefreshSpeakerPortrait();
        }
    }
}
