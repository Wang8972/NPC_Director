using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.UI;
using UnityEngine.TextCore.LowLevel;
using UnityEngine.UI;

namespace LastLight
{
    /// <summary>The player-facing client. The local backend owns every world transition.</summary>
    [DefaultExecutionOrder(-1000)]
    public sealed partial class LastLightApp : MonoBehaviour
    {
        TrainWorld world;
        PerformancePlayer performancePlayer;
        LastLightClient client;
        BackendLauncher launcher;
        GameView view;
        Canvas canvas;
        RectTransform canvasRect, hud, drawer, drawerContent, modalRoot, titleRoot, dialogueContent, roomButtons, actorButtons;
        ScrollRect drawerScroll, dialogueScroll;
        TextMeshProUGUI objectiveText, chapterText, roomText, modeText, statusText, targetText, dialogueStatus, drawerTitle;
        TMP_InputField chatInput;
        Button sendButton, stopTalkButton, nextTextButton, continueButton;
        RawImage portrait;
        GameObject busyIndicator;
        string selectedNpc = "lin", selectedTarget = "lin", drawerTab = "", endpoint;
        string statusMessage = "", sessionId = "", currentExecutionId = "", connectionError = "";
        bool busy, animating, modalOpen, titleOpen = true, serviceReady, directorReady, completing, skipAnimation;
        bool lowQuality, reducedMotion, instantText, quitWhenSaved;
        bool qaCapture, qaPauseRequested;
        float volume, statusUntil;
        int sessionGeneration;
        readonly HashSet<string> completedAnimations = new HashSet<string>();
        readonly List<string> audience = new List<string>();
        Coroutine executionRoutine;

        void Awake()
        {
            Application.runInBackground = true;
            Application.targetFrameRate = 60;
            PresentationClock.Reset();
            qaCapture=Array.IndexOf(Environment.GetCommandLineArgs(),"--qa-capture")>=0;
            endpoint = PlayerPrefs.GetString("lastlight.endpoint", "http://127.0.0.1:8766");
            if (!LastLightClient.IsLoopbackEndpoint(endpoint)) endpoint = "http://127.0.0.1:8766";
            volume = PlayerPrefs.GetFloat("lastlight.volume", .65f);
            lowQuality = PlayerPrefs.GetInt("lastlight.low_quality", 0) == 1;
            reducedMotion = PlayerPrefs.GetInt("lastlight.reduced_motion", 0) == 1;
            instantText = PlayerPrefs.GetInt("lastlight.instant_text", 0) == 1;
            client = gameObject.AddComponent<LastLightClient>(); client.Endpoint = endpoint;
            launcher = gameObject.AddComponent<BackendLauncher>();
            world = GetComponent<TrainWorld>(); if (world == null) world = gameObject.AddComponent<TrainWorld>();
            performancePlayer=gameObject.AddComponent<PerformancePlayer>();performancePlayer.Initialize(world);
            CreateFont(); BuildInterface();
            world.Initialize(SelectTarget, MoveRoom); world.SetQuality(lowQuality); world.SetVolume(volume); world.SetInputBlocked(true);
            ShowTitle();
            if(!qaCapture)StartCoroutine(ConnectService(true));
        }

        void CreateFont()
        {
            var source = Resources.Load<Font>("Fonts/Chinese");
            if (source == null) source = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            UiFactory.Font = TMP_FontAsset.CreateFontAsset(source, 40, 5, GlyphRenderMode.SDFAA, 2048, 2048, AtlasPopulationMode.Dynamic, true);
            UiFactory.Font.name = "LastLight Chinese Dynamic"; UiFactory.Font.isMultiAtlasTexturesEnabled = true;
        }

        void Update()
        {
            PresentationClock.Paused=modalOpen||titleOpen||qaPauseRequested||(!Application.isFocused&&!qaCapture);
            world?.SetPresentationPaused(PresentationClock.Paused);
            PresentationClock.Tick(Time.unscaledDeltaTime);
            ReleaseChatFocusForGameplayIntent();
            bool typing = IsTyping();
            if (world != null) world.SetInputBlocked(titleOpen || introPlaying || modalOpen || busy || animating || typing || view == null || view.execution != null || !string.IsNullOrEmpty(view.ending));
            if (statusText != null && !string.IsNullOrEmpty(statusMessage) && Time.unscaledTime > statusUntil)
            {
                statusMessage = ""; statusText.text = DefaultStatus();
            }
            var keyboard = Keyboard.current;
            if (keyboard == null) return;
            if(introPlaying)
            {
                if(keyboard.escapeKey.wasPressedThisFrame)FinishIntro(true);
                else if(keyboard.spaceKey.wasPressedThisFrame)AdvanceIntro();
                return;
            }
            if (keyboard.escapeKey.wasPressedThisFrame)
            {
                if (typing) { EventSystem.current.SetSelectedGameObject(null); return; }
                if (modalOpen) { CloseModal(); return; }
                if (titleOpen) return;
                if (animating) { ShowExecutionControls(); return; }
                ShowPause();
            }
            if (typing || modalOpen || titleOpen) return;
            if ((keyboard.ctrlKey.isPressed || keyboard.leftMetaKey.isPressed || keyboard.rightMetaKey.isPressed) && keyboard.sKey.wasPressedThisFrame) SaveProgress();
            if (keyboard.tabKey.wasPressedThisFrame) ToggleDrawer("journal");
            if (keyboard.spaceKey.wasPressedThisFrame && (revealingText || awaitingAdvance)) AdvanceDialogue();
        }

        bool IsTyping()
        {
            if (EventSystem.current == null || EventSystem.current.currentSelectedGameObject == null) return false;
            var input = EventSystem.current.currentSelectedGameObject.GetComponent<TMP_InputField>();
            return input != null && input.isFocused;
        }

        /// <summary>
        /// TMP keeps an input field selected after the player clicks the 3D scene.  Because
        /// world input is deliberately disabled while typing, that otherwise creates a
        /// focus trap: the scene click, WASD and E can never reach TrainWorld.  Release an
        /// empty chat field when the player clearly intends to return to exploration.
        /// Non-empty text is preserved so ordinary Latin/IME entry is never mistaken for
        /// movement.
        /// </summary>
        void ReleaseChatFocusForGameplayIntent()
        {
            if (chatInput == null || !chatInput.isFocused || EventSystem.current == null) return;
            if (titleOpen || introPlaying || modalOpen) return;

            var pointer = Pointer.current;
            if (pointer != null && pointer.press.wasPressedThisFrame)
            {
                Vector2 screenPoint = pointer.position.ReadValue();
                if (!RectTransformUtility.RectangleContainsScreenPoint(chatInput.transform as RectTransform, screenPoint, null))
                {
                    chatInput.DeactivateInputField();
                    EventSystem.current.SetSelectedGameObject(null);
                    return;
                }
            }

            // An empty input still owns keyboard input: WASD/E may be the
            // first character of a message or an IME composition.  Only an
            // outside click (above) or Escape (Update) releases that focus.
        }

        IEnumerator ConnectService(bool launch)
        {
            SetStatus("正在连接本机救援服务…", 60);
            ApiResponse health = null;
            client.Get("/health", r => health = r);
            while (health == null) yield return null;
            if (!health.ok && health.network_error && launch && launcher.TryStart(endpoint))
            {
                for (int attempt = 0; attempt < 12 && !health.ok; attempt++)
                {
                    yield return new WaitForSecondsRealtime(attempt < 2 ? .5f : 1f);
                    health = null; client.Get("/health", r => health = r);
                    while (health == null) yield return null;
                }
            }
            serviceReady = health != null && health.ok; directorReady = serviceReady && health.director_ready;
            connectionError=serviceReady?"":health?.error??launcher.Status;
            SetStatus(serviceReady ? "本机服务已连接" : connectionError + "\n可在设置中检查连接。", serviceReady ? 5 : 60);
            RefreshTitleState();
        }

        void NewSession(string mode)
        {
            if (!serviceReady) { ShowConnection(); return; }
            if (busy) return;
            StopSessionActivity(); var generation = sessionGeneration;
            busy = true; SetStatus(mode == "live" ? "正在建立真实 AI 救援会话…" : "正在建立预设演练…", 60);
            client.Post("/sessions", new CreateSessionRequest { mode = mode }, response =>
            {
                if (generation != sessionGeneration) return;
                busy = false;
                if (!response.ok || response.view == null) { ShowError(response.error ?? "会话创建失败"); return; }
                BindSession(response.view, response.job, true);
            });
        }

        void LoadSession(string id, bool restore = false)
        {
            if (busy || string.IsNullOrEmpty(id)) return;
            StopSessionActivity(); var generation = sessionGeneration; busy = true;
            client.Get("/sessions/" + Uri.EscapeDataString(id), response =>
            {
                if (generation != sessionGeneration) return;
                busy = false;
                if (!response.ok || response.view == null) { ShowError(response.error ?? "无法读取存档"); return; }
                BindSession(response.view, response.job);
                if (restore) RestoreBackup();
            });
        }

        // Keep this single-argument entry point stable for deterministic Windows QA capture.
        void OpenSession(GameView next)
        {
            StopSessionActivity();BindSession(next);
        }

        void BindSession(GameView next, TalkJob pendingJob = null, bool fresh = false)
        {
            sessionId = next.session_id; view = null; selectedTarget = selectedNpc = "lin";
            if(!qaCapture){PlayerPrefs.SetString("lastlight.last_session", sessionId); PlayerPrefs.Save();}
            titleOpen = false; titleRoot.gameObject.SetActive(false); hud.gameObject.SetActive(true); CloseModal();
            ClearConversation(); draftSteps.Clear(); ApplyView(next, true);
            if (view.dialogue.Length == 0)
            {
                var room = view.rooms.FirstOrDefault(r => r.id == view.room_id);
                AddConversationLine(new DialogueLine { id = "opening-" + sessionId, npc_id = "narrator", speaker = "此刻", source = "narrative", text = room?.description ?? "列车停了下来。先观察身边的人和物件，了解发生了什么。" }, false);
            }
            SetStatus(next.mode == "live" ? "真实 AI 模式 · 交谈不会推进危险" : "预设演练 · 对白为作者预写，非 AI 生成", 12);
            if (pendingJob != null) AdoptJob(pendingJob);
            if (!string.IsNullOrEmpty(next.ending) && !HasActiveTalk) ShowEnding();
            else if (next.execution != null && !string.IsNullOrEmpty(next.execution.id) && !HasActiveTalk) ShowResumeExecution(next.execution);
            else if(fresh&&!HasActiveTalk&&!qaCapture)BeginIntro();
        }

        void ApplyView(GameView next, bool allowOlder = false)
        {
            if (next == null || (!string.IsNullOrEmpty(sessionId) && next.session_id != sessionId)) return;
            if (!allowOlder && view != null && next.revision < view.revision) return;
            if (!allowOlder && view != null && next.revision == view.revision)
            {
                // Job polling must not rebuild scene props or erase a focused plan editor.
                SyncDialogue(next.dialogue); return;
            }
            view = next; sessionId = next.session_id;
            NormalizeView(); world.Apply(view);
            var present = view.actors.Where(a => IsNpc(a.id) && a.room_id == view.room_id).ToArray();
            if (!present.Any(a => a.id == selectedNpc)) selectedNpc = present.Length == 0 ? "" : present[0].id;
            audience.RemoveAll(id => !present.Any(a => a.id == id) || id == selectedNpc);
            if (string.IsNullOrEmpty(selectedTarget) || (!view.actors.Any(a => a.id == selectedTarget) && !view.objects.Any(o => o.id == selectedTarget))) selectedTarget = selectedNpc;
            RefreshHud(); SyncDialogue(view.dialogue); RefreshDrawer();
        }

        void NormalizeView()
        {
            view.actors = view.actors ?? Array.Empty<ActorView>(); view.rooms = view.rooms ?? Array.Empty<RoomView>();
            view.objects = view.objects ?? Array.Empty<ObjectView>(); view.actions = view.actions ?? Array.Empty<ActionView>();
            view.inventory = view.inventory ?? Array.Empty<ItemView>(); view.journal = view.journal ?? Array.Empty<JournalView>();
            view.dialogue = view.dialogue ?? Array.Empty<DialogueLine>(); view.plans = view.plans ?? Array.Empty<PlanView>();
            view.topics = view.topics ?? Array.Empty<TopicView>(); view.epilogues = view.epilogues ?? Array.Empty<DialogueLine>();
        }

        void SelectTarget(string id)
        {
            if (view == null || busy || animating || modalOpen || titleOpen) return;
            if (HasActiveTalk) { SetStatus("先完成当前交谈，或点击「停止」。", 5); return; }
            if (id == "xiaoman") id = "child";
            if (id == "mother") id = "oxygen";
            selectedTarget = id;
            if (IsNpc(id))
            {
                selectedNpc = id; audience.Remove(id); world.Focus(id); RefreshHud();
                if (drawerTab == "target" || drawerTab == "topics") RefreshDrawer();
                SetStatus("正在与" + ActorName(id) + "交谈。可自由提问，也可查看话题。", 6);
            }
            else { world.Focus(id); ToggleDrawer("target", true); }
        }

        void MoveRoom(string id)
        {
            if (!CanAct() || HasActiveTalk || id == view.room_id) return;
            var room = view.rooms.FirstOrDefault(r => r.id == id);
            if (room == null || !room.accessible) { SetStatus("这条通路目前尚未开放。请查看附近的门与可行方案。", 8); return; }
            Mutate("move", new MoveRequest { room_id = id, expected_revision = view.revision }, _ =>
            {
                selectedTarget = selectedNpc; world.PlayCue("click");
            });
        }

        bool CanAct() => view != null && view.execution == null && !busy && !animating && !titleOpen && string.IsNullOrEmpty(view.ending);

        void Inspect(string target)
        {
            if (!CanAct() || HasActiveTalk) return;
            Mutate("inspect", new InspectRequest { target_id = target, expected_revision = view.revision }, _ => world.PlayCue("click"));
        }

        void Mutate(string operation, object request, Action<ApiResponse> after = null)
        {
            if (busy || string.IsNullOrEmpty(sessionId)) return;
            busy = true; RefreshInteractivity(); var generation = sessionGeneration;
            client.Post(SessionPath(operation), request, response =>
            {
                if (generation != sessionGeneration) return;
                busy = false;
                if (response.view != null) ApplyView(response.view);
                RefreshInteractivity();
                if (!response.ok) { ShowError(response.error ?? "操作没有得到确认"); return; }
                if (response.job != null) AdoptJob(response.job);
                after?.Invoke(response);
                if (!string.IsNullOrEmpty(view?.ending) && !HasActiveTalk && !animating) ShowEnding();
            });
        }

        string SessionPath(string operation = "") => "/sessions/" + Uri.EscapeDataString(sessionId) + (string.IsNullOrEmpty(operation) ? "" : "/" + operation);

        void RefreshProgress(Action after = null)
        {
            if (string.IsNullOrEmpty(sessionId) || busy) return;
            busy = true; var generation = sessionGeneration;
            client.Get(SessionPath(), response =>
            {
                if (generation != sessionGeneration) return;
                busy = false;
                if (!response.ok || response.view == null) { ShowError(response.error ?? "读取进度失败"); return; }
                ApplyView(response.view, true);
                if (response.job != null) AdoptJob(response.job);
                else if (HasActiveTalk) ReleaseLocalTalk();
                after?.Invoke();
            });
        }

        void SaveProgress()
        {
            if (view == null || view.execution != null || busy || animating || HasActiveTalk) return;
            Mutate("save", null, _ => { SetStatus("手动备份已保存。每次确认的世界变化也会自动保存。", 8); world.PlayCue("click"); if (quitWhenSaved) ReturnToTitle(); });
        }

        void RestoreBackup()
        {
            if (view == null || busy || animating) return;
            Confirm("恢复手动备份", "恢复会替换当前会话的自动进度。已经交付的后续谈话也将以备份为准。", "恢复备份", () =>
            {
                CancelTalk(); sessionGeneration++; ClearConversation(); draftSteps.Clear();
                Mutate("restore", null, result => { if (result.view != null) ApplyView(result.view, true); SetStatus("已恢复备份", 6); });
            });
        }

        void StopSessionActivity()
        {
            performancePlayer?.StopAll("session_changed");
            if(introPlaying)FinishIntro(false);
            CancelTalk(); sessionGeneration++; cancellingTalk = false; busy = false; animating = false; completing = false;
            if (executionRoutine != null) StopCoroutine(executionRoutine);
            executionRoutine = null; currentExecutionId = ""; completedAnimations.Clear();
        }

        void ReturnToTitle()
        {
            if (animating || busy) return;
            StopSessionActivity(); quitWhenSaved = false; CloseModal(); ShowTitle();
        }

        void SetStatus(string message, float seconds = 7)
        {
            statusMessage = message ?? ""; statusUntil = Time.unscaledTime + seconds;
            if (statusText != null) statusText.text = statusMessage;
        }
        string DefaultStatus() => view == null ? "本机运行 · 你的选择留下后果" : (view.mode == "live" ? "真实 AI 对话" : "预设演练 · 非 AI") + "   /   交谈、调查、移动不消耗行动时间";
        static bool IsNpc(string id) => id == "lin" || id == "zhou" || id == "chen" || id == "xu";
        string ActorName(string id)
        {
            var actor = view?.actors?.FirstOrDefault(a => a.id == id); if (actor != null) return actor.name;
            switch (id) { case "player": return "你"; case "lin": return "林岚"; case "zhou": return "周屿"; case "chen": return "陈默"; case "xu": return "许宁"; case "mother": return "许宁的母亲"; case "xiaoman": return "小满"; case "train": return "列车公用"; case "passenger05": return "05号车厢乘客"; case "passenger07": return "07号车厢乘客"; case "internal": return "内置电池"; default: return string.IsNullOrEmpty(id) ? "尚不清楚" : id; }
        }
        string ActionLabel(string id) => view?.actions?.FirstOrDefault(a => a.id == id)?.label ?? id;
        string RoomName(string id) => view?.rooms?.FirstOrDefault(r => r.id == id)?.title ?? id;
        string TargetName(string id) => view?.objects?.FirstOrDefault(o => o.id == id)?.label ?? ActorName(id);

        void RefreshInteractivity()
        {
            bool canTalk = CanAct() && !HasActiveTalk && !string.IsNullOrEmpty(selectedNpc);
            if (sendButton != null) sendButton.interactable = canTalk;
            if (chatInput != null) chatInput.interactable = canTalk;
            if (stopTalkButton != null) stopTalkButton.gameObject.SetActive(HasActiveTalk);
            if (busyIndicator != null) busyIndicator.SetActive(busy || animating || HasActiveTalk);
        }

        void OnApplicationFocus(bool focus) { if (!focus && view != null && !titleOpen) SetStatus("当前画面已保留；离开窗口不会推进危险。", 8); }
    }
}
