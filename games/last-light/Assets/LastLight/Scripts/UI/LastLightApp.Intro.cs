using System.Collections;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace LastLight
{
    public sealed partial class LastLightApp
    {
        bool introPlaying, introReady;
        int introBeat;
        Coroutine introRoutine;
        RectTransform introRoot;
        GameObject introCard;
        Image introShade;
        TextMeshProUGUI introSpeaker, introText, introProgress;
        Button introNext;

        // The authored prologue only states publicly visible circumstances. It performs no
        // model call, ACK, knowledge edit or physical action, and never replays on Continue.
        void BeginIntro()
        {
            if(qaCapture)return;
            introPlaying=true;introReady=false;introBeat=0;
            hud.gameObject.SetActive(false);
            introRoot=UiFactory.Rect("Opening",canvasRect);UiFactory.Fill(introRoot);
            introShade=UiFactory.Panel("Blackout",introRoot,Color.black,true,false);
            UiFactory.Fill(introShade.rectTransform);
            var skip=UiFactory.Button("Skip opening",introRoot,"跳过开场",()=>FinishIntro(true),false,46);
            UiFactory.Place((RectTransform)skip.transform,Vector2.one,Vector2.one,-34,-28,155,46);
            var chapter=UiFactory.Text("Prologue",introRoot,"序 幕  /  停车之后",28,UiFactory.Amber);
            UiFactory.Place(chapter.rectTransform,new Vector2(0,1),new Vector2(0,1),48,-40,640,50);
            var card=UiFactory.Panel("Opening conversation",introRoot,new Color(.025f,.05f,.072f,.95f));
            UiFactory.Place(card.rectTransform,new Vector2(.5f,0),new Vector2(.5f,0),0,64,1180,272);
            introCard=card.gameObject;introCard.SetActive(false);
            introSpeaker=UiFactory.Text("Speaker",card.transform,"",27,UiFactory.Amber,FontStyles.Bold);
            UiFactory.Place(introSpeaker.rectTransform,new Vector2(0,1),new Vector2(0,1),30,-22,850,42);
            introText=UiFactory.Text("Prologue text",card.transform,"",31);
            UiFactory.Fill(introText.rectTransform,30,30,79,74);
            introText.lineSpacing=3;
            introProgress=UiFactory.Text("Beat",card.transform,"",21,UiFactory.Muted);
            UiFactory.Place(introProgress.rectTransform,Vector2.zero,Vector2.zero,30,20,600,35);
            introNext=UiFactory.Button("Continue opening",card.transform,"继续",AdvanceIntro,true,48);
            UiFactory.Place((RectTransform)introNext.transform,new Vector2(1,0),new Vector2(1,0),-28,18,188,48);
            world.SetInputBlocked(true);world.PlayCue("brake");world.Focus("player");
            introRoutine=StartCoroutine(FadeIntoTrain());
        }

        IEnumerator FadeIntoTrain()
        {
            float elapsed=0, duration=reducedMotion?.05f:.85f;
            while(introPlaying&&elapsed<duration)
            {
                elapsed+=PresentationClock.Delta;
                introShade.color=new Color(.005f,.012f,.02f,Mathf.Lerp(1,.13f,Mathf.Clamp01(elapsed/duration)));
                yield return null;
            }
            if(!introPlaying)yield break;
            introCard.SetActive(true);introReady=true;introRoutine=null;ShowIntroBeat();
        }

        void AdvanceIntro()
        {
            if(!introPlaying||!introReady)return;
            if(introBeat>=2){FinishIntro(true);return;}
            introBeat++;ShowIntroBeat();
        }

        void ShowIntroBeat()
        {
            string speaker, text, actor;
            if(introBeat==0)
            {
                speaker="一阵突如其来的制动";actor="player";
                text="你从半睡中惊醒。窗外只剩隧道壁，顶灯暗下去，应急灯亮了。\n你只是这趟列车的一名普通乘客。";
            }
            else if(introBeat==1)
            {
                speaker="林岚 · 乘务员";actor="lin";
                text="请先留在车厢里。外面的情况还没有核实。\n我知道大家着急，但现在不能贸然开门。";
            }
            else
            {
                speaker="周屿 · 一名焦急的乘客";actor="zhou";
                text="那就去核实！不能只有一句「请等待」。\n我真的不能一直坐在这里。";
            }
            introSpeaker.text=speaker;introSpeaker.color=UiFactory.ActorColor(actor);
            introText.text=text;introProgress.text=(introBeat+1)+" / 3  ·  先看清附近，再听他们把话说完";
            UiFactory.SetLabel(introNext,introBeat==2?"起身查看":"继续");
            world.Focus(actor);
            if(actor!="player")world.Emote(actor,introBeat==2?"angry":"concerned");
        }

        void FinishIntro(bool showGuide)
        {
            if(!introPlaying)return;
            introPlaying=false;introReady=false;
            if(introRoutine!=null)StopCoroutine(introRoutine);introRoutine=null;
            if(introRoot!=null){introRoot.gameObject.SetActive(false);Destroy(introRoot.gameObject);}
            introRoot=null;hud.gameObject.SetActive(true);
            if(view!=null){world.Apply(view);RefreshHud();}
            SetStatus("先与身边的人交谈，或点击附近的物件查看。",10);
            if(showGuide)ShowFirstRunGuide();
        }

        void ShowFirstRunGuide(bool force=false)
        {
            if(!force&&PlayerPrefs.GetInt("lastlight.tutorial_seen",0)==1)return;
            PlayerPrefs.SetInt("lastlight.tutorial_seen",1);PlayerPrefs.Save();
            var body=OpenModal("先看清，再行动",830,850);
            UiFactory.FlowText(body,"从林岚、周屿和附近的物件开始。你随时可以关闭这份引导。",25,UiFactory.Muted);
            UiFactory.FlowText(body,"01  移动与调查",25,UiFactory.Amber);
            UiFactory.FlowText(body,"WASD 移动，点击人物或物件走近；E 互动。查看物件能获得有来源的线索，左侧通路图连接已经开放的区域。",24);
            UiFactory.FlowText(body,"02  听他们说，也说出你的想法",25,UiFactory.Amber);
            UiFactory.FlowText(body,"在底部自由输入，或从「话题」开始。人物说完后点击「继续」；空格可以显示全文或继续。",24);
            UiFactory.FlowText(body,"03  把想法变成协作计划",25,UiFactory.Amber);
            UiFactory.FlowText(body,"行动可以加入计划。安排负责人、协助者和先后依赖，检查条件与本批成本，再确认执行。",24);
            UiFactory.FlowText(body,"04  留出思考的时间",25,UiFactory.Amber);
            UiFactory.FlowText(body,"走动、查看物件、阅读、交谈和等待 AI 都不推进危险。检测、检修等实际行动按你确认的成本推进局势。",24);
            UiFactory.Button("Begin exploring",body,titleOpen?"返回标题":"开始探索",CloseModal,true,58);
        }
    }
}
