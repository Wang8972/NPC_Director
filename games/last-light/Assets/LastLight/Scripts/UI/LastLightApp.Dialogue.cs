using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace LastLight
{
    public sealed partial class LastLightApp
    {
        TalkJob activeJob;
        Coroutine pollRoutine, deliveryRoutine;
        int talkGeneration;
        bool jobStarting, revealingText, awaitingAdvance, advanceRequested, cancellingTalk;
        readonly Queue<DialogueLine> pendingLines = new Queue<DialogueLine>();
        readonly HashSet<string> queuedLineIds = new HashSet<string>();
        readonly HashSet<string> acknowledgedLineIds = new HashSet<string>();
        readonly HashSet<string> shownDialogueIds = new HashSet<string>();
        readonly Dictionary<string, TMP_Text> dialogueBodies = new Dictionary<string, TMP_Text>();
        readonly List<DialogueLine> shownDialogue = new List<DialogueLine>();
        TMP_Text revealingBody;
        PlanStep[] suggestedSteps = Array.Empty<PlanStep>();
        string suggestedTitle = "", lastPlayerText = "";
        bool HasActiveTalk => jobStarting || cancellingTalk || deliveryRoutine != null || pendingLines.Count > 0 ||
            (activeJob != null && activeJob.status != "completed" && activeJob.status != "failed" && activeJob.status != "cancelled");

        void SendChat() => BeginTalk(chatInput == null ? "" : chatInput.text, "");

        void BeginTalk(string text, string topicId)
        {
            text = (text ?? "").Trim();
            if (!CanAct() || HasActiveTalk || string.IsNullOrEmpty(selectedNpc) || string.IsNullOrEmpty(text)) return;
            if (!view.actors.Any(a => a.id == selectedNpc && a.room_id == view.room_id))
            { SetStatus("请先走近这个人，再开始交谈。", 6); return; }
            chatInput.text = ""; UnityEngine.EventSystems.EventSystem.current.SetSelectedGameObject(null);
            jobStarting = true; int generation = sessionGeneration; int conversation = ++talkGeneration;
            queuedLineIds.Clear(); acknowledgedLineIds.Clear(); pendingLines.Clear(); activeJob = null;
            suggestedSteps = Array.Empty<PlanStep>(); suggestedTitle = "";
            lastPlayerText = text;
            AddConversationLine(new DialogueLine { id = "local-player-" + Guid.NewGuid().ToString("N"), npc_id = "player", speaker = "你", text = text, source = "narrative" }, false);
            dialogueStatus.text = view.mode == "live" ? "正在听取你的话…  ·  等待不会推进危险" : "正在读取预设演练对白…  ·  非 AI";
            RefreshInteractivity(); RefreshHud();
            string talkPath = SessionPath("talk");
            client.Post(talkPath, new TalkRequest
            {
                npc_id = selectedNpc, text = text, topic_id = topicId ?? "", audience = audience.ToArray(), expected_revision = view.revision
            }, response =>
            {
                if (generation != sessionGeneration || conversation != talkGeneration)
                {
                    if (response.job != null) client.Post(talkPath + "/" + Uri.EscapeDataString(response.job.id) + "/cancel", null, _ => { });
                    return;
                }
                jobStarting = false;
                if (response.view != null) ApplyView(response.view);
                if (!response.ok || response.job == null)
                {
                    dialogueStatus.text = "交谈没有开始。世界状态未因这句话自动改变。";
                    RefreshInteractivity(); ShowError(response.error ?? "没有收到对话任务。"); return;
                }
                AcceptJob(response.job);
                pollRoutine = StartCoroutine(PollJob(generation, conversation));
            });
        }

        IEnumerator PollJob(int generation, int conversation)
        {
            while (generation == sessionGeneration && conversation == talkGeneration && activeJob != null)
            {
                bool terminal = IsTerminal(activeJob.status);
                if (terminal && pendingLines.Count == 0 && deliveryRoutine == null)
                {
                    dialogueStatus.text = activeJob.status == "completed" ? "对话已结束 · 可以继续提问或安排实际行动" : activeJob.status == "cancelled" ? "对话已停止" : "AI 对话未完成 · 可重新提问";
                    if (activeJob.status == "failed") SetStatus("AI 对话未完成：" + activeJob.error + "。没有切换为脚本 AI。", 18);
                    RefreshHud(); RefreshInteractivity();
                    if (suggestedSteps.Length > 0) { ToggleDrawer("plan", true); SetStatus("对方提出了一份行动建议。查看、修改并确认后才会执行。", 12); }
                    if (!string.IsNullOrEmpty(view?.ending)) ShowEnding();
                    pollRoutine = null; yield break;
                }
                yield return new WaitForSecondsRealtime(.65f);
                var jobId = activeJob.id; ApiResponse response = null;
                client.Get(SessionPath("talk/" + Uri.EscapeDataString(jobId)), r => response = r);
                while (response == null && generation == sessionGeneration && conversation == talkGeneration) yield return null;
                if (generation != sessionGeneration || conversation != talkGeneration) yield break;
                if (response == null || !response.ok || response.job == null)
                {
                    dialogueStatus.text = "对话连接中断 · 尚未显示的话不会被确认";
                    SetStatus(response?.error ?? "无法获取对话进度", 10);
                    yield return new WaitForSecondsRealtime(2);
                    continue;
                }
                if (response.view != null) ApplyView(response.view);
                AcceptJob(response.job);
            }
            pollRoutine = null;
        }

        static bool IsTerminal(string status) => status == "completed" || status == "failed" || status == "cancelled";

        void AdoptJob(TalkJob job)
        {
            if (job == null || string.IsNullOrEmpty(job.id)) return;
            if (activeJob != null && activeJob.id == job.id)
            {
                AcceptJob(job);
                if (pollRoutine == null) pollRoutine = StartCoroutine(PollJob(sessionGeneration, talkGeneration));
                return;
            }
            CancelTalk();
            cancellingTalk = false; queuedLineIds.Clear(); acknowledgedLineIds.Clear(); pendingLines.Clear(); activeJob = null;
            if (job.source == "live")
                foreach (var line in view.dialogue)
                    if (!string.IsNullOrEmpty(line.id)) { queuedLineIds.Add(line.id); acknowledgedLineIds.Add(line.id); }
            AcceptJob(job);
            pollRoutine = StartCoroutine(PollJob(sessionGeneration, talkGeneration));
        }

        void AcceptJob(TalkJob job)
        {
            if (job == null || (activeJob != null && activeJob.id != job.id)) return;
            activeJob = job;
            foreach (var line in job.lines ?? Array.Empty<DialogueLine>())
            {
                if (line == null || string.IsNullOrEmpty(line.id) || !queuedLineIds.Add(line.id)) continue;
                pendingLines.Enqueue(line);
            }
            if (job.suggested_steps != null && job.suggested_steps.Length > 0)
            { suggestedSteps = job.suggested_steps; suggestedTitle = job.suggested_title ?? "协作建议"; }
            if (deliveryRoutine == null && pendingLines.Count > 0) deliveryRoutine = StartCoroutine(DeliverLines(sessionGeneration, talkGeneration, job.id));
            if (!revealingText && !awaitingAdvance && job.status == "running") dialogueStatus.text = "正在回应与协调…  ·  等待不会推进危险";
            RefreshInteractivity();
        }

        IEnumerator DeliverLines(int generation, int conversation, string jobId)
        {
            yield return null;
            while (pendingLines.Count > 0 && DialogueCurrent(generation, conversation))
            {
                var line = pendingLines.Dequeue();
                if (line.delivered || line.delivery_status == "delivered")
                {
                    if (!shownDialogueIds.Contains(DialogueKey(line))) AddConversationLine(line, false);
                    acknowledgedLineIds.Add(line.id); continue;
                }
                bool presented = false;
                yield return PresentLine(line, generation, conversation, jobId, ok => presented = ok);
                if (!DialogueCurrent(generation, conversation)) yield break;
                if (!presented) { CancelTalk(); yield break; }
            }
            deliveryRoutine = null; revealingText = awaitingAdvance = false;
            nextTextButton.gameObject.SetActive(false); ClearCurrentPerformance(); RefreshInteractivity();
        }

        void AdvanceDialogue()
        {
            if (revealingText) RevealNow();
            else if (awaitingAdvance && !modalOpen && !titleOpen) advanceRequested = true;
        }
        void RevealNow()
        {
            if (!revealingText) { if (awaitingAdvance) advanceRequested = true; return; }
            revealingText = false;
            if (revealingBody != null) revealingBody.maxVisibleCharacters = int.MaxValue;
        }

        void CancelTalk()
        {
            if (cancellingTalk) return;
            if(playingHasStarted&&!string.IsNullOrEmpty(playingLineId))
                SendPlaybackEvent(playingJobId,playingLineId,"interrupted",playingPerformance!=null&&playingPerformance.visualsSkipped,_=>{});
            ClearCurrentPerformance();
            var job = activeJob; bool wasActive = HasActiveTalk;
            ++talkGeneration; jobStarting = false;
            if (pollRoutine != null) StopCoroutine(pollRoutine); pollRoutine = null;
            if (deliveryRoutine != null) StopCoroutine(deliveryRoutine); deliveryRoutine = null;
            pendingLines.Clear(); queuedLineIds.RemoveWhere(id => !acknowledgedLineIds.Contains(id));
            activeJob = null; revealingText = awaitingAdvance = false;
            if (nextTextButton != null) nextTextButton.gameObject.SetActive(false);
            if (job != null && !IsTerminal(job.status) && !string.IsNullOrEmpty(sessionId))
            {
                cancellingTalk = true; var generation = sessionGeneration; var conversation = talkGeneration;
                client.Post(SessionPath("talk/" + Uri.EscapeDataString(job.id) + "/cancel"), null, response =>
                {
                    if (generation != sessionGeneration || conversation != talkGeneration) return;
                    cancellingTalk = false;
                    if (response.view != null) ApplyView(response.view);
                    if (!response.ok)
                    {
                        activeJob = job;
                        SetStatus("停止尚未得到确认。请重试「停止」，或检查连接并读取进度。", 15);
                    }
                    RefreshInteractivity(); RefreshHud();
                });
            }
            if (wasActive)
            {
                if (dialogueStatus != null) dialogueStatus.text = "交谈已停止 · 尚未确认的话不会形成新安排";
                SetStatus("已停止继续播放。服务已经确认的安排与行动会保留。", 8);
            }
            RefreshInteractivity();
        }

        void ReleaseLocalTalk()
        {
            ClearCurrentPerformance();
            // GET session has confirmed there is no active server job. Invalidate stale callbacks
            // without issuing another cancellation against a restored timeline.
            ++talkGeneration; jobStarting = cancellingTalk = false;
            if (pollRoutine != null) StopCoroutine(pollRoutine);
            if (deliveryRoutine != null) StopCoroutine(deliveryRoutine);
            pollRoutine = deliveryRoutine = null;
            pendingLines.Clear(); activeJob = null; revealingText = awaitingAdvance = false;
            nextTextButton.gameObject.SetActive(false);
            foreach (var line in view.dialogue)
                if (!string.IsNullOrEmpty(line.id) && dialogueBodies.TryGetValue(line.id,out var body))
                    body.maxVisibleCharacters = int.MaxValue;
            RefreshHud(); RefreshInteractivity();
        }

        TMP_Text AddConversationLine(DialogueLine line, bool animate)
        {
            string id = DialogueKey(line);
            if (!shownDialogueIds.Add(id))
            {
                if (dialogueBodies.TryGetValue(id, out var existing)) return existing;
                return UiFactory.FlowText(dialogueContent, line.text, 25);
            }
            shownDialogue.Add(line);
            var row = UiFactory.Column("Line " + id, dialogueContent, 3);
            var source = line.source == "live" ? "" : line.source == "rehearsal" ? "  ·  预设演练" : "";
            var speaker = string.IsNullOrEmpty(line.speaker) ? ActorName(line.npc_id) : line.speaker;
            UiFactory.FlowText(row, speaker + source, 20, UiFactory.ActorColor(line.npc_id));
            var body = UiFactory.FlowText(row, line.text ?? "", 25, line.npc_id == "player" ? UiFactory.Muted : UiFactory.TextColor);
            dialogueBodies[id] = body;
            if (!animate) body.maxVisibleCharacters = int.MaxValue;
            StartCoroutine(ScrollDialogueBottom());
            return body;
        }

        void SyncDialogue(DialogueLine[] lines)
        {
            foreach (var line in lines ?? Array.Empty<DialogueLine>())
            {
                if (line == null || string.IsNullOrEmpty(line.text)) continue;
                if (shownDialogueIds.Contains(DialogueKey(line))) continue;
                if ((line.npc_id == "player" || line.speaker == "你") && line.text == lastPlayerText)
                { shownDialogueIds.Add(DialogueKey(line)); lastPlayerText = ""; continue; }
                AddConversationLine(line, false);
            }
        }
        static string DialogueKey(DialogueLine line) => string.IsNullOrEmpty(line.id) ? (line.npc_id + "|" + line.speaker + "|" + line.text) : line.id;
        IEnumerator ScrollDialogueBottom() { yield return null; Canvas.ForceUpdateCanvases(); if (dialogueScroll != null) dialogueScroll.verticalNormalizedPosition = 0; }
        void ClearConversation()
        {
            shownDialogue.Clear(); shownDialogueIds.Clear(); dialogueBodies.Clear(); queuedLineIds.Clear(); acknowledgedLineIds.Clear(); pendingLines.Clear();
            lastPlayerText = ""; suggestedSteps = Array.Empty<PlanStep>();
            if (dialogueContent != null) UiFactory.Clear(dialogueContent);
        }

        void RenderTopics()
        {
            drawerTitle.text = "与" + ActorName(selectedNpc) + "交谈";
            if (string.IsNullOrEmpty(selectedNpc)) { UiFactory.FlowText(drawerContent, "当前附近没有可以交谈的人。", 25); return; }
            UiFactory.FlowText(drawerContent, view.mode == "live" ? "自由表达疑问、担忧或计划。下面的话题只帮助开口。" : "预设演练使用作者编写的对白。自由输入不会被假装成 AI 推理。", 24, UiFactory.Muted);
            foreach (var topic in view.topics.Where(t => t.npc_id == selectedNpc || string.IsNullOrEmpty(t.npc_id)))
            {
                var captured = topic;
                var button = UiFactory.Button("Topic " + topic.id, drawerContent, topic.label, () => BeginTalk(captured.label, captured.id), false, 58);
                button.interactable = CanAct() && !HasActiveTalk;
            }
            if (!view.topics.Any(t => t.npc_id == selectedNpc || string.IsNullOrEmpty(t.npc_id)))
            {
                foreach (var question in new[] { "你刚才看到了什么？", "现在最需要先做什么？", "你能帮忙做哪些事情？" })
                {
                    var captured = question; var button = UiFactory.Button("Question", drawerContent, captured, () => BeginTalk(captured, ""), false, 58);
                    button.interactable = CanAct() && !HasActiveTalk;
                }
            }
            Divider(drawerContent);
            UiFactory.FlowText(drawerContent, "邀请在场的人一起听", 23, UiFactory.Amber);
            var nearby = view.actors.Where(a => IsNpc(a.id) && a.id != selectedNpc && a.room_id == view.room_id).ToArray();
            if (nearby.Length == 0) UiFactory.FlowText(drawerContent, "其他人不在近旁。消息不会自动传到别的车厢。", 22, UiFactory.Muted);
            foreach (var person in nearby)
            {
                var id = person.id;
                var toggle = UiFactory.Toggle(drawerContent, person.name, audience.Contains(id), enabled => { if (enabled && !audience.Contains(id)) audience.Add(id); else if (!enabled) audience.Remove(id); });
                toggle.interactable = !HasActiveTalk;
            }
        }
    }
}
