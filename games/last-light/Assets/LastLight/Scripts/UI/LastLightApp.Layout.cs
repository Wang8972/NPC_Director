using System;
using System.Linq;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem.UI;
using UnityEngine.UI;

namespace LastLight
{
    public sealed partial class LastLightApp
    {
        void BuildInterface()
        {
            if (EventSystem.current == null)
            {
                var events = new GameObject("LastLight EventSystem", typeof(EventSystem), typeof(InputSystemUIInputModule));
                events.GetComponent<InputSystemUIInputModule>().AssignDefaultActions();
            }
            else
            {
                var legacy = EventSystem.current.GetComponent<StandaloneInputModule>();
                if (legacy != null) { legacy.enabled = false; Destroy(legacy); }
                if (EventSystem.current.GetComponent<InputSystemUIInputModule>() == null)
                    EventSystem.current.gameObject.AddComponent<InputSystemUIInputModule>().AssignDefaultActions();
            }
            canvasRect = UiFactory.Rect("LastLight Interface", transform);
            canvas = canvasRect.gameObject.AddComponent<Canvas>(); canvas.renderMode = RenderMode.ScreenSpaceOverlay; canvas.sortingOrder = 30;
            var scaler = canvasRect.gameObject.AddComponent<CanvasScaler>(); scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920, 1080); scaler.matchWidthOrHeight = .5f;
            canvasRect.gameObject.AddComponent<GraphicRaycaster>();
            hud = UiFactory.Rect("In Game", canvasRect); UiFactory.Fill(hud);
            BuildHeader(); BuildMap(); BuildDialogue(); BuildDrawer();
            titleRoot = UiFactory.Rect("Title", canvasRect); UiFactory.Fill(titleRoot);
            modalRoot = UiFactory.Rect("Modal", canvasRect); UiFactory.Fill(modalRoot); modalRoot.gameObject.SetActive(false);
        }

        void BuildHeader()
        {
            var top = UiFactory.Panel("Header", hud, new Color(.025f, .048f, .068f, .91f), false, false);
            top.rectTransform.anchorMin = new Vector2(0, 1); top.rectTransform.anchorMax = Vector2.one; top.rectTransform.pivot = new Vector2(.5f, 1);
            top.rectTransform.anchoredPosition = Vector2.zero; top.rectTransform.sizeDelta = new Vector2(0, 116);
            var logo = UiFactory.Text("Logo", top.transform, "余 灯", 36, UiFactory.Amber, FontStyles.Bold);
            UiFactory.Place(logo.rectTransform, new Vector2(0, .5f), new Vector2(0, .5f), 30, 5, 130, 50);
            chapterText = UiFactory.Text("Chapter", top.transform, "LAST LIGHT", 21, UiFactory.Muted);
            UiFactory.Place(chapterText.rectTransform, new Vector2(0, .5f), new Vector2(0, .5f), 182, 27, 720, 30);
            objectiveText = UiFactory.Text("Objective", top.transform, "", 23);
            objectiveText.lineSpacing = 2; objectiveText.maxVisibleLines = 2; objectiveText.overflowMode = TextOverflowModes.Ellipsis;
            UiFactory.Place(objectiveText.rectTransform, new Vector2(0, .5f), new Vector2(0, .5f), 182, -21, 1100, 60);
            modeText = UiFactory.Text("Mode", top.transform, "", 20, UiFactory.Blue); modeText.alignment = TextAlignmentOptions.MidlineRight;
            UiFactory.Place(modeText.rectTransform, new Vector2(1, .5f), new Vector2(1, .5f), -27, 25, 540, 32);
            var bar = UiFactory.Row("Tools", top.transform, 8, 40);
            UiFactory.Place(bar, new Vector2(1, .5f), new Vector2(1, .5f), -24, -20, 530, 42);
            UiFactory.Button("Plan", bar, "计划", () => ToggleDrawer("plan"), false, 42);
            UiFactory.Button("History", bar, "对白", () => ToggleDrawer("history"), false, 42);
            UiFactory.Button("Notes", bar, "笔记", () => ToggleDrawer("journal"), false, 42);
            UiFactory.Button("Items", bar, "物品", () => ToggleDrawer("inventory"), false, 42);
            UiFactory.Button("Pause", bar, "暂停", ShowPause, false, 42);
            var location = UiFactory.Panel("Location", hud, new Color(.035f, .065f, .09f, .82f), false);
            UiFactory.Place(location.rectTransform, new Vector2(0, 1), new Vector2(0, 1), 26, -136, 355, 76);
            roomText = UiFactory.Text("Room", location.transform, "", 27, UiFactory.TextColor);
            UiFactory.Fill(roomText.rectTransform, 20, 15, 10, 10);
            var hint = UiFactory.Text("Explore Hint", hud, "WASD 移动   ·   点击人物 / 物件   ·   E 交互", 21, new Color(.85f, .88f, .9f, .8f));
            UiFactory.Place(hint.rectTransform, new Vector2(0, 0), new Vector2(0, 0), 32, 388, 820, 35);
        }

        void BuildMap()
        {
            var panel = UiFactory.Panel("Route", hud, new Color(.035f,.065f,.09f,.84f));
            UiFactory.Place(panel.rectTransform, new Vector2(0, 1), new Vector2(0, 1), 26, -226, 184, 345);
            var title = UiFactory.Text("Route title", panel.transform, "列车通路", 22, UiFactory.Muted);
            UiFactory.Place(title.rectTransform, new Vector2(0, 1), new Vector2(0, 1), 16, -13, 150, 32);
            roomButtons = UiFactory.Column("Rooms", panel.transform, 7);
            UiFactory.Fill(roomButtons, 12, 12, 55, 12);
        }

        void BuildDialogue()
        {
            var panel = UiFactory.Panel("Conversation", hud, new Color(.028f, .053f, .074f, .97f));
            panel.rectTransform.anchorMin = new Vector2(0, 0); panel.rectTransform.anchorMax = new Vector2(1, 0); panel.rectTransform.pivot = Vector2.zero;
            panel.rectTransform.offsetMin = new Vector2(24, 43); panel.rectTransform.offsetMax = new Vector2(-510, 372);
            var character = UiFactory.Rect("Portrait", panel.transform);
            UiFactory.Place(character, new Vector2(0, 1), new Vector2(0, 1), 18, -18, 76, 76);
            portrait = character.gameObject.AddComponent<RawImage>(); portrait.color = Color.white; portrait.raycastTarget = false;
            targetText = UiFactory.Text("Selected Character", panel.transform, "林岚", 28, UiFactory.Blue, FontStyles.Bold);
            UiFactory.Place(targetText.rectTransform, new Vector2(0, 1), new Vector2(0, 1), 111, -17, 420, 37);
            dialogueStatus = UiFactory.Text("Dialogue Status", panel.transform, "", 20, UiFactory.Muted);
            UiFactory.Place(dialogueStatus.rectTransform, new Vector2(0, 1), new Vector2(0, 1), 111, -54, 760, 30);
            actorButtons = UiFactory.Row("Nearby People", panel.transform, 7, 37);
            UiFactory.Place(actorButtons, new Vector2(1, 1), new Vector2(1, 1), -16, -20, 410, 38);
            dialogueScroll = UiFactory.Scroll("Dialogue History", panel.transform, out dialogueContent, 12, 4);
            UiFactory.Fill((RectTransform)dialogueScroll.transform, 24, 24, 99, 85);
            var inputRow = UiFactory.Row("Input", panel.transform, 9, 54);
            inputRow.anchorMin = new Vector2(0, 0); inputRow.anchorMax = new Vector2(1, 0); inputRow.pivot = Vector2.zero;
            inputRow.offsetMin = new Vector2(20, 18); inputRow.offsetMax = new Vector2(-20, 72);
            var topics = UiFactory.Button("Topics", inputRow, "话题", () => ToggleDrawer("topics"), false, 54);
            topics.GetComponent<LayoutElement>().preferredWidth = 85; topics.GetComponent<LayoutElement>().flexibleWidth = 0;
            chatInput = UiFactory.Input("Say", inputRow, "说出你的想法、疑问或救援方案…", 54);
            chatInput.GetComponent<LayoutElement>().flexibleWidth = 1; chatInput.onSubmit.AddListener(_ => SendChat());
            sendButton = UiFactory.Button("Send", inputRow, "交谈", SendChat, true, 54);
            sendButton.GetComponent<LayoutElement>().preferredWidth = 88; sendButton.GetComponent<LayoutElement>().flexibleWidth = 0;
            stopTalkButton = UiFactory.Button("Stop", inputRow, "停止", CancelTalk, false, 54);
            stopTalkButton.GetComponent<LayoutElement>().preferredWidth = 85; stopTalkButton.GetComponent<LayoutElement>().flexibleWidth = 0;
            nextTextButton = UiFactory.Button("ShowText", panel.transform, "显示全文", AdvanceDialogue, false, 33);
            UiFactory.Place((RectTransform)nextTextButton.transform, new Vector2(1, 0), new Vector2(1, 0), -23, 79, 130, 33);
            nextTextButton.gameObject.SetActive(false);
            skipPerformanceButton=UiFactory.Button("Skip performance",panel.transform,"略过动作",SkipCurrentPerformance,false,33);
            UiFactory.Place((RectTransform)skipPerformanceButton.transform,new Vector2(1,0),new Vector2(1,0),-164,79,130,33);
            skipPerformanceButton.gameObject.SetActive(false);
            statusText = UiFactory.Text("Status", hud, DefaultStatus(), 21, UiFactory.Muted);
            UiFactory.Place(statusText.rectTransform, new Vector2(0, 0), Vector2.zero, 28, 5, 1740, 32);
            busyIndicator = UiFactory.Text("Busy", hud, "●", 24, UiFactory.Amber).gameObject;
            UiFactory.Place((RectTransform)busyIndicator.transform, new Vector2(1, 0), new Vector2(1, 0), -30, 4, 35, 35);
            busyIndicator.SetActive(false);
        }

        void BuildDrawer()
        {
            var panel = UiFactory.Panel("Side Panel", hud, UiFactory.PanelColor);
            drawer = panel.rectTransform; drawer.anchorMin = new Vector2(1, 0); drawer.anchorMax = Vector2.one; drawer.pivot = Vector2.one;
            drawer.offsetMin = new Vector2(-486, 43); drawer.offsetMax = new Vector2(-24, -118);
            drawerTitle = UiFactory.Text("Heading", drawer, "", 28, UiFactory.Amber, FontStyles.Bold);
            UiFactory.Place(drawerTitle.rectTransform, new Vector2(0, 1), new Vector2(0, 1), 22, -22, 345, 44);
            var close = UiFactory.Button("Close", drawer, "收起", () => ToggleDrawer(drawerTab), false, 39);
            UiFactory.Place((RectTransform)close.transform, Vector2.one, Vector2.one, -18, -22, 75, 39);
            drawerScroll = UiFactory.Scroll("Details", drawer, out drawerContent, 14, 4);
            UiFactory.Fill((RectTransform)drawerScroll.transform, 18, 18, 85, 18);
            drawer.gameObject.SetActive(false);
        }

        void RefreshHud()
        {
            if (view == null) return;
            chapterText.text = view.chapter ?? "异常停车";
            objectiveText.text = view.objective ?? "观察周围，了解发生了什么。";
            modeText.text = (view.mode == "live" ? "真实 AI · NPC DIRECTOR" : "预设演练 · 非 AI") + "   /   行动时段 " + view.tick;
            var room = view.rooms.FirstOrDefault(r => r.id == view.room_id);
            roomText.text = room == null ? "列车内" : room.title + (room.smoke > 0 ? "\n" + (room.smoke == 1 ? "已观察到烟气" : "烟气明显加重") : "");
            roomText.fontSize = room != null && room.smoke > 0 ? 22 : 27; roomText.lineSpacing = 0;
            UiFactory.Clear(roomButtons);
            foreach (var r in view.rooms)
            {
                var captured = r;
                string label = r.id == "tunnel" ? "避险通道" : r.title;
                var button = UiFactory.Button("Room " + r.id, roomButtons, (r.id == view.room_id ? "● " : "") + label, () => MoveRoom(captured.id), r.id == view.room_id, 48);
                button.interactable = r.accessible && CanAct() && !HasActiveTalk;
            }
            UiFactory.Clear(actorButtons);
            foreach (var actor in view.actors.Where(a => IsNpc(a.id) && a.room_id == view.room_id))
            {
                var id = actor.id; var button = UiFactory.Button("Speak " + id, actorButtons, actor.name, () => SelectTarget(id), id == selectedNpc, 37);
                button.interactable = !HasActiveTalk && !busy && !animating;
            }
            var selected = view.actors.FirstOrDefault(a => a.id == selectedNpc);
            RefreshSpeakerPortrait();
            if (!HasActiveTalk) dialogueStatus.text = selected == null ? "走近人物后可以交谈。查看场景中的物件获取线索。" : "人物会记得已交付的承诺。行动需要另行确认。";
            if (string.IsNullOrEmpty(statusMessage)) statusText.text = DefaultStatus();
            RefreshInteractivity();
        }

        void ToggleDrawer(string tab, bool force = false)
        {
            if (view == null || titleOpen) return;
            if (!force && drawer.gameObject.activeSelf && drawerTab == tab) { drawer.gameObject.SetActive(false); drawerTab = ""; return; }
            drawerTab = tab; drawer.gameObject.SetActive(true); RefreshDrawer(); world.PlayCue("click");
        }

        void RefreshDrawer()
        {
            if (view == null || string.IsNullOrEmpty(drawerTab) || !drawer.gameObject.activeSelf) return;
            UiFactory.Clear(drawerContent);
            switch (drawerTab)
            {
                case "target": RenderTarget(); break;
                case "topics": RenderTopics(); break;
                case "journal": RenderJournal(); break;
                case "inventory": RenderInventory(); break;
                case "plan": RenderPlans(); break;
                case "history": RenderHistory(); break;
            }
        }

        void RenderTarget()
        {
            var obj = view.objects.FirstOrDefault(o => o.id == selectedTarget);
            drawerTitle.text = obj?.label ?? ActorName(selectedTarget);
            if (obj != null)
            {
                UiFactory.FlowText(drawerContent, obj.description, 25);
                UiFactory.FlowText(drawerContent, "状态 · " + StateLabel(obj.state), 22, UiFactory.Blue);
                var inspect = UiFactory.Button("Inspect", drawerContent, "仔细观察  ·  不消耗时间", () => Inspect(obj.id), false);
                inspect.interactable = obj.interactable && CanAct() && !HasActiveTalk;
            }
            else
            {
                var actor = view.actors.FirstOrDefault(a => a.id == selectedTarget);
                if (actor != null) UiFactory.FlowText(drawerContent, actor.role + (string.IsNullOrEmpty(actor.task_status) ? "" : "\n当前 · " + StateLabel(actor.task_status)), 25);
            }
            var options = view.actions.Where(a => a.target_id == selectedTarget).ToArray();
            if (options.Length > 0) UiFactory.FlowText(drawerContent, "可以尝试", 22, UiFactory.Muted);
            foreach (var action in options) RenderActionCard(drawerContent, action);
            if (obj == null && IsNpc(selectedTarget)) UiFactory.Button("Topics", drawerContent, "交谈与推荐话题", () => ToggleDrawer("topics", true));
            if (options.Length == 0 && obj != null) UiFactory.FlowText(drawerContent, "有些行动需要先调查、取得合作或准备工具。笔记会记录已经确认的线索。", 23, UiFactory.Muted);
        }

        void RenderActionCard(Transform parent, ActionView action)
        {
            var card = UiFactory.Panel("Action " + action.id, parent, UiFactory.CardColor);
            var column = card.rectTransform;
            var layout = card.gameObject.AddComponent<VerticalLayoutGroup>();
            layout.spacing = 9; layout.padding = new RectOffset(15,15,15,15);
            layout.childControlWidth = layout.childControlHeight = true;
            layout.childForceExpandWidth = true; layout.childForceExpandHeight = false;
            UiFactory.FlowText(column, action.label, 25, UiFactory.TextColor);
            UiFactory.FlowText(column, action.description, 22, UiFactory.Muted);
            if (!action.enabled) UiFactory.FlowText(column, "尚需 · " + action.blocked_reason, 21, UiFactory.Amber);
            var button = UiFactory.Button("Plan Action", column, action.duration == 0 ? "加入计划" : "加入计划  ·  " + action.duration + " 时段", () => AddDraft(action), action.enabled, 42);
            button.interactable = CanAct() && !HasActiveTalk;
        }

        void RenderJournal()
        {
            drawerTitle.text = "调查笔记";
            UiFactory.FlowText(drawerContent, "亲眼所见、他人陈述与承诺分开记录。未核实的说法不等于事实。", 23, UiFactory.Muted);
            if (view.journal.Length == 0) UiFactory.FlowText(drawerContent, "还没有记录。走近车厢里的物件，先观察周围。", 25);
            foreach (var entry in view.journal.Reverse())
            {
                string kind = entry.kind == "verified" ? "已核实" : entry.kind == "observed" ? "亲眼观察" : entry.kind == "promise" ? "承诺" : "他人陈述";
                UiFactory.FlowText(drawerContent, kind + "  /  " + entry.source + "  /  时段 " + entry.tick, 20, entry.kind == "promise" ? UiFactory.Amber : UiFactory.Blue);
                UiFactory.FlowText(drawerContent, entry.title, 26, UiFactory.TextColor);
                UiFactory.FlowText(drawerContent, entry.text, 24, UiFactory.Muted);
                Divider(drawerContent);
            }
        }

        void RenderInventory()
        {
            drawerTitle.text = "物品与持有人";
            UiFactory.FlowText(drawerContent, "这里展示已经观察到的物品。口头同意借用后，仍需实际交接。", 23, UiFactory.Muted);
            if (view.inventory.Length == 0) UiFactory.FlowText(drawerContent, "尚未发现可用物品。", 25);
            foreach (var item in view.inventory)
            {
                UiFactory.FlowText(drawerContent, item.label, 26);
                UiFactory.FlowText(drawerContent, "持有 · " + (string.IsNullOrEmpty(item.holder_id) ? RoomName(item.room_id) : ActorName(item.holder_id)) + "\n归属 · " + ActorName(item.owner_id), 23, UiFactory.Muted);
                UiFactory.FlowText(drawerContent, "状态 · " + StateLabel(item.state) + (item.charge >= 0 ? "\n剩余电量 · " + item.charge : "") + (string.IsNullOrEmpty(item.connected_to) ? "" : "\n连接 · " + TargetName(item.connected_to)), 23, UiFactory.Blue);
                Divider(drawerContent);
            }
        }

        void RenderHistory()
        {
            drawerTitle.text = "对白记录";
            UiFactory.FlowText(drawerContent, "已确认的对话与现场记录。正在说的话仍显示在底部。",23,UiFactory.Muted);
            if (view.dialogue.Length == 0) UiFactory.FlowText(drawerContent,"还没有已经完成的对话记录。",25);
            foreach (var line in view.dialogue)
            {
                string speaker = string.IsNullOrEmpty(line.speaker) ? ActorName(line.npc_id) : line.speaker;
                UiFactory.FlowText(drawerContent,speaker+(line.source=="rehearsal"?" · 预设演练":""),23,UiFactory.ActorColor(line.npc_id));
                UiFactory.FlowText(drawerContent,line.text,25);
                Divider(drawerContent);
            }
        }

        static void Divider(Transform parent)
        {
            var line = UiFactory.Panel("Divider", parent, new Color(.3f,.4f,.45f,.35f), false, false);
            line.gameObject.AddComponent<LayoutElement>().preferredHeight = 1;
        }
        static string StateLabel(string state)
        {
            switch (state)
            {
                case "open": return "已打开"; case "closed": return "已关闭"; case "jammed": return "被卡住";
                case "cleared": return "障碍已清理"; case "isolated": return "已隔离供电"; case "live": return "仍然带电";
                case "powered": return "已通电"; case "unpowered": return "未通电"; case "tested": return "已完成复测";
                case "repaired": return "已修复，待复测"; case "unexamined": return "尚待检查";
                case "clear": return "通路畅通"; case "cluttered": return "有杂物阻挡";
                case "running": return "正在运行"; case "stored": return "存放中"; case "held": return "有人持有";
                case "connected": return "已接入"; case "depleted": return "电量耗尽"; case "consumed": return "已使用";
                case "lit": return "已有照明"; case "dark": return "缺少照明"; case "observed": return "已观察";
                case "available": return "可观察"; case "executing": return "执行任务中"; case "idle": return "待命";
                case "completed": return "已完成"; case "waiting": return "等待"; case "stopped": return "已停止";
                case "running_internal": return "运行中 · 内部供电";
                case "running_backup": return "运行中 · 备用电源供电";
                case "connected_radio": return "已接入通信设备"; case "connected_medical": return "已接入照护设备";
                case "needs_interface": return "电源正常，接口待接续"; case "ready": return "已就绪";
                case "diagnosed": return "已定位故障"; case "isolated_diagnosed": return "已定位且隔离";
                case "empty": return "已取走"; case "tools": return "架上 · 工具包";
                case "lamp": return "架上 · 手电"; case "spares": return "架上 · 密封备件";
                case "tools,lamp": return "架上 · 工具包、手电";
                case "tools,spares": return "架上 · 工具包、密封备件";
                case "lamp,spares": return "架上 · 手电、密封备件";
                case "tools,lamp,spares": return "架上 · 工具包、手电、密封备件";
                default: return string.IsNullOrEmpty(state) ? "尚待确认" : state;
            }
        }
    }
}
