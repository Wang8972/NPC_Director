using System;
using System.Linq;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace LastLight
{
    public sealed partial class LastLightApp
    {
        int modalVersion;
        TextMeshProUGUI titleConnection;
        Button titleStartButton;

        RectTransform OpenModal(string title, float width = 790, float height = 690)
        {
            modalVersion++; modalOpen = true; modalRoot.gameObject.SetActive(true); UiFactory.Clear(modalRoot);
            var shade = UiFactory.Panel("Shade", modalRoot, new Color(.008f, .018f, .026f, .78f), true, false);
            UiFactory.Fill(shade.rectTransform);
            var panel = UiFactory.Panel("Dialog", modalRoot, UiFactory.PanelColor);
            float availableWidth = canvasRect.rect.width > 100 ? canvasRect.rect.width : 1920;
            float availableHeight = canvasRect.rect.height > 100 ? canvasRect.rect.height : 1080;
            UiFactory.Place(panel.rectTransform, new Vector2(.5f,.5f), new Vector2(.5f,.5f), 0, 0, Mathf.Min(width, availableWidth-48), Mathf.Min(height, availableHeight-54));
            var heading = UiFactory.Text("Heading", panel.transform, title, 32, UiFactory.Amber, FontStyles.Bold);
            UiFactory.Place(heading.rectTransform, new Vector2(0,1), new Vector2(0,1), 28, -23, width-130, 53);
            heading.enableWordWrapping=false; heading.overflowMode=TextOverflowModes.Ellipsis;
            var close = UiFactory.Button("Close", panel.transform, "返回", CloseModal, false, 39);
            UiFactory.Place((RectTransform)close.transform, Vector2.one, Vector2.one, -23, -25, 73, 39);
            var scroll = UiFactory.Scroll("Body", panel.transform, out var body, 17, 4);
            UiFactory.Fill((RectTransform)scroll.transform, 26, 26, 90, 26);
            world?.SetInputBlocked(true); return body;
        }
        void CloseModal()
        {
            modalVersion++; modalOpen = false;
            if (modalRoot != null) modalRoot.gameObject.SetActive(false);
            if (UnityEngine.EventSystems.EventSystem.current != null)
                UnityEngine.EventSystems.EventSystem.current.SetSelectedGameObject(null);
            if (!titleOpen && view?.execution != null && !animating && !completing && !busy)
            {
                ToggleDrawer("plan", true);
                SetStatus("还有一批已经安排的行动。请在计划栏继续，或取消未完成的安排。",10);
            }
        }
        void Confirm(string title, string explanation, string accept, Action action)
        {
            var body = OpenModal(title, 740, 455);
            UiFactory.FlowText(body, explanation, 26);
            UiFactory.Button("Accept", body, accept, () => { CloseModal(); action?.Invoke(); }, true, 55);
            UiFactory.Button("Back", body, "返回", CloseModal);
        }
        void ShowError(string error)
        {
            var body = OpenModal("暂时无法继续", 790, 540);
            UiFactory.FlowText(body, string.IsNullOrWhiteSpace(error) ? "服务尚未确认这次操作。" : error, 26);
            UiFactory.FlowText(body, "只有服务已经确认的行动才会改变世界。可以读取最新进度，或检查本机连接。", 23, UiFactory.Muted);
            if (!string.IsNullOrEmpty(sessionId))
                UiFactory.Button("Refresh", body, "读取最新进度", () => { CloseModal(); RefreshProgress(); }, true);
            UiFactory.Button("Connection", body, "检查连接", ShowConnection);
            UiFactory.Button("Back", body, "返回游戏", CloseModal);
            world?.PlayCue("alert");
        }

        void ShowTitle()
        {
            titleOpen = true; hud.gameObject.SetActive(false); drawer.gameObject.SetActive(false); drawerTab = "";
            titleRoot.gameObject.SetActive(true); UiFactory.Clear(titleRoot);
            var shade = UiFactory.Panel("Title shade", titleRoot, new Color(.012f,.028f,.041f,.48f), true, false);
            UiFactory.Fill(shade.rectTransform);
            var band = UiFactory.Panel("Title band", titleRoot, new Color(.026f,.052f,.072f,.94f), true, false);
            band.rectTransform.anchorMin = Vector2.zero; band.rectTransform.anchorMax = new Vector2(.44f,1); UiFactory.Fill(band.rectTransform);
            band.rectTransform.anchorMax = new Vector2(.44f,1);
            var brand = UiFactory.Text("Title", titleRoot, "余 灯", 132, UiFactory.Amber, FontStyles.Bold);
            UiFactory.Place(brand.rectTransform, new Vector2(0,1), new Vector2(0,1), 90, -82, 620, 166);
            var english = UiFactory.Text("English", titleRoot, "L A S T   L I G H T", 30, UiFactory.Blue);
            UiFactory.Place(english.rectTransform, new Vector2(0,1), new Vector2(0,1), 105, -252, 620, 45);
            var tagline = UiFactory.Text("Tagline", titleRoot, "火车停下了。\n你们的故事，还在继续。", 37, UiFactory.TextColor);
            UiFactory.Place(tagline.rectTransform, new Vector2(0,1), new Vector2(0,1), 105, -325, 630, 130);
            var description = UiFactory.Text("Description", titleRoot, "一次异常停车，几个互不相识的人。\n走近他们，组织救援，承担选择的后果。", 25, UiFactory.Muted);
            UiFactory.Place(description.rectTransform, new Vector2(0,1), new Vector2(0,1), 105, -465, 635, 100);
            var buttons = UiFactory.Column("Start options", titleRoot, 12);
            UiFactory.Place(buttons, new Vector2(0,0), new Vector2(0,0), 105, 120, 530, 370);
            titleStartButton = UiFactory.Button("New live", buttons, "开始新的旅程", () => NewSession("live"), true, 65);
            continueButton = UiFactory.Button("Continue", buttons, "继续上次旅程", () => LoadSession(PlayerPrefs.GetString("lastlight.last_session","")), false, 58);
            var row = UiFactory.Row("Title menus", buttons, 10, 47);
            UiFactory.Button("Saves", row, "存档", ShowSessionPicker, false, 47);
            UiFactory.Button("Settings", row, "设置", ShowSettings, false, 47);
            UiFactory.Button("Help", row, "帮助", ShowHelp, false, 47);
            UiFactory.Button("Quit", row, "退出", QuitGame, false, 47);
            UiFactory.Button("Rehearsal", buttons, "预设演练 · 无 AI 的规则体验", () => Confirm("预设演练", "这个模式使用预写对白与推荐话题，便于体验救援规则。真实 AI 推理与动态协商需要从主入口开始。", "进入预设演练", () => NewSession("rehearsal")), false, 48);
            titleConnection = UiFactory.FlowText(buttons, "正在连接本机服务…", 21, UiFactory.Muted);
            var corner = UiFactory.Text("Credits", titleRoot, "一场关于信任、责任与共同选择的群像冒险\n环境声音 · 无自动朗读", 23, new Color(.84f,.88f,.88f,.8f));
            corner.alignment = TextAlignmentOptions.BottomRight;
            UiFactory.Place(corner.rectTransform, Vector2.one, Vector2.one, -58, -875, 800, 92);
            RefreshTitleState();
        }

        void RefreshTitleState()
        {
            if (titleStartButton != null) titleStartButton.interactable = !busy;
            if (continueButton != null) continueButton.interactable = !busy && !string.IsNullOrEmpty(PlayerPrefs.GetString("lastlight.last_session",""));
            if (titleConnection != null)
                titleConnection.text = serviceReady ? (directorReady ? "本机服务已连接 · 真实 AI 可用" : "本机服务已连接 · AI 配置请在设置中检查") : "尚未连接本机服务 · 可在设置中重试";
        }

        void ShowPause()
        {
            if (view == null || titleOpen) { ShowSettings(); return; }
            if (animating) { ShowExecutionControls(); return; }
            var body = OpenModal(string.IsNullOrEmpty(view.ending) ? "暂停" : "旅程已结束", 690, 740);
            UiFactory.FlowText(body, "阅读、交谈与离开窗口都不会推进危险。每次确认的世界变化会自动保存。", 25, UiFactory.Muted);
            UiFactory.Button("Resume", body, "回到列车", CloseModal, true, 56);
            if (!string.IsNullOrEmpty(view.ending)) UiFactory.Button("Ending", body, "重看结局", ShowEnding);
            var save = UiFactory.Button("Manual backup", body, "创建手动备份", () => { CloseModal(); SaveProgress(); });
            save.interactable = !busy && !HasActiveTalk && view.execution == null;
            var restore = UiFactory.Button("Restore", body, "恢复手动备份", RestoreBackup); restore.interactable = !busy && !HasActiveTalk;
            UiFactory.Button("Settings", body, "设置", ShowSettings);
            UiFactory.Button("Help", body, "操作与玩法", ShowHelp);
            var leave = UiFactory.Button("To title", body, "返回标题 · 自动进度保留", () => Confirm("返回标题", "已确认的进度会保留。尚在交谈中的未交付内容将停止。", "返回标题", ReturnToTitle));
            leave.interactable = !busy;
        }

        void ShowSettings()
        {
            var body = OpenModal("设置", 800, 830);
            UiFactory.FlowText(body, "环境音量", 26, UiFactory.Amber);
            UiFactory.Slider(body, volume, value => { volume = value; world.SetVolume(value); PlayerPrefs.SetFloat("lastlight.volume",value); });
            UiFactory.Toggle(body, "降低阴影质量", lowQuality, value => { lowQuality=value; world.SetQuality(value); PlayerPrefs.SetInt("lastlight.low_quality",value?1:0); });
            UiFactory.Toggle(body, "对白立即显示全文", instantText, value => { instantText=value; PlayerPrefs.SetInt("lastlight.instant_text",value?1:0); });
            UiFactory.Toggle(body, "简化行动演出（结果相同）", reducedMotion, value => { reducedMotion=value; PlayerPrefs.SetInt("lastlight.reduced_motion",value?1:0); });
            UiFactory.FlowText(body, "分辨率", 26, UiFactory.Amber);
            var resolutions = UiFactory.Row("Resolution", body, 10, 48);
            UiFactory.Button("720p", resolutions, "1280 × 720", () => Screen.SetResolution(1280,720,FullScreenMode.Windowed), false,48);
            UiFactory.Button("1080p", resolutions, "1920 × 1080", () => Screen.SetResolution(1920,1080,FullScreenMode.Windowed),false,48);
            UiFactory.Button("Fullscreen", resolutions, "全屏", () => Screen.fullScreenMode=FullScreenMode.FullScreenWindow,false,48);
            Divider(body);
            UiFactory.FlowText(body, "本机服务", 26, UiFactory.Amber);
            UiFactory.FlowText(body, serviceReady ? (directorReady ? "已连接 · 真实 AI 可用" : "已连接 · 尚需配置 AI 提供商") : "尚未连接", 24, UiFactory.Muted);
            UiFactory.Button("Connection settings", body, "连接与启动设置", ShowConnection);
            UiFactory.FlowText(body, "游戏不提供配音或 TTS。聊天内容和物理行动分别确认；对方提出建议后，需要你检查并开始执行。", 23, UiFactory.Muted);
            UiFactory.Button("Save preferences", body, "完成", () => { PlayerPrefs.Save(); CloseModal(); }, true);
        }

        void ShowConnection()
        {
            var body = OpenModal("本机服务", 850, 780);
            UiFactory.FlowText(body, serviceReady ? "服务已连接" : string.IsNullOrEmpty(connectionError)?launcher.Status:connectionError, 25, UiFactory.Amber);
            UiFactory.FlowText(body, "完整发行包会尝试自动启动后台。AI 的模型和凭据在服务端配置；不需要填写到游戏窗口。", 24, UiFactory.Muted);
            UiFactory.FlowText(body, "服务地址", 23);
            var address = UiFactory.Input("Endpoint", body, "http://127.0.0.1:8765",54); address.text = endpoint;
            UiFactory.FlowText(body, "可选：本机 Python 可执行文件路径", 23);
            var python = UiFactory.Input("Python", body, "发行包通常无需填写",54); python.text=PlayerPrefs.GetString("lastlight.python","");
            UiFactory.Button("Connect", body, "保存并重新连接", () =>
            {
                if (!LastLightClient.IsLoopbackEndpoint(address.text)) { SetStatus("请输入本机 HTTP 地址，例如 http://127.0.0.1:8765。",10); return; }
                endpoint=address.text.TrimEnd('/'); client.Endpoint=endpoint;
                PlayerPrefs.SetString("lastlight.endpoint",endpoint); PlayerPrefs.SetString("lastlight.python",python.text.Trim()); PlayerPrefs.Save();
                CloseModal(); StartCoroutine(ConnectService(true));
            }, true);
            UiFactory.FlowText(body, "如果 AI 未就绪，请按发行包 README 完成服务端配置，再重试。在线失败会明确报错，不会悄悄替换成脚本对白。", 24, UiFactory.Muted);
            UiFactory.Button("Back", body, "返回", CloseModal);
        }

        void ShowSessionPicker()
        {
            if (!serviceReady) { ShowConnection(); return; }
            var body=OpenModal("保存的旅程",850,850); var version=modalVersion;
            UiFactory.FlowText(body,"正在读取存档…",25,UiFactory.Muted);
            client.Get("/sessions",response =>
            {
                if (!modalOpen || version!=modalVersion) return;
                UiFactory.Clear(body);
                if (!response.ok) { UiFactory.FlowText(body,response.error,25,UiFactory.Danger); return; }
                var sessions=response.sessions??Array.Empty<SessionInfo>();
                if(sessions.Length==0) { UiFactory.FlowText(body,"还没有保存的旅程。开始新游戏后会自动保存进度。",25); return; }
                foreach(var session in sessions)
                {
                    var captured=session;
                    UiFactory.FlowText(body,session.chapter+"  ·  行动时段 "+session.tick,26,UiFactory.Amber);
                    UiFactory.FlowText(body,(session.mode=="live"?"真实 AI":"预设演练")+"  /  "+session.updated_at,22,UiFactory.Muted);
                    UiFactory.Button("Load "+session.session_id,body,"继续这次旅程",()=>{ CloseModal(); LoadSession(captured.session_id); },true);
                    Divider(body);
                }
            });
        }

        void ShowHelp()
        {
            var body=OpenModal("走近他们，一起找到出路",880,890);
            UiFactory.FlowText(body,"探索",27,UiFactory.Amber);
            UiFactory.FlowText(body,"WASD 移动，点击人物或物件让角色走近；E 与附近目标互动。左侧通路图切换已经开放的区域。走动、查看和阅读不推进危险。",25);
            UiFactory.FlowText(body,"交谈",27,UiFactory.Amber);
            UiFactory.FlowText(body,"选择身边的人，在底部输入你的想法。话题侧栏可以帮助开口，也能邀请在场的人共同参与。每句话显示后点击「继续」。空格可显示全文或继续。",25);
            UiFactory.FlowText(body,"计划与后果",27,UiFactory.Amber);
            UiFactory.FlowText(body,"人物建议可以载入草案，也可以从物件或行动列表手动添加。调整执行者、协助者及步骤依赖，检查成本后再确认。没有依赖的任务可并行；每批完成后先看变化，再继续下一批。",25);
            UiFactory.FlowText(body,"信息与物品",27,UiFactory.Amber);
            UiFactory.FlowText(body,"笔记区分观察、他人陈述、核实与承诺。TAB 打开笔记。物品栏显示已经看到的物品及持有人；答应借用不等于已经交出。关注门、灯、设备与人物的实际变化。",25);
            UiFactory.FlowText(body,"暂停与保存",27,UiFactory.Amber);
            UiFactory.FlowText(body,"Esc 打开暂停或关闭窗口。Ctrl / Command + S 创建手动备份；菜单可以恢复。自动保存保留每次已确认的进度。离开窗口、模型等待和读对白都不会偷偷消耗救援时间。",25);
            UiFactory.FlowText(body,"真实 AI 与预设演练",27,UiFactory.Amber);
            UiFactory.FlowText(body,"主模式使用真实 NPC Director。预设演练使用明确标注的作者对白，适合检查规则和操作。任何模式下，行动是否成功都由同一套世界规则确认。",25);
            UiFactory.Button("Replay guide",body,"重看首次操作引导",()=>ShowFirstRunGuide(true));
            UiFactory.Button("Understood",body,"回到现场",CloseModal,true,56);
        }

        void ShowEnding()
        {
            if(view==null||string.IsNullOrEmpty(view.ending)) return;
            var body=OpenModal(string.IsNullOrEmpty(view.ending_title)?"这次旅程的终点":view.ending_title,1020,920);
            UiFactory.FlowText(body,"余 灯  /  LAST LIGHT",23,UiFactory.Blue);
            UiFactory.FlowText(body,view.ending_text,29);
            Divider(body);
            foreach(var epilogue in view.epilogues)
            {
                UiFactory.FlowText(body,string.IsNullOrEmpty(epilogue.speaker)?ActorName(epilogue.npc_id):epilogue.speaker,27,UiFactory.ActorColor(epilogue.npc_id));
                UiFactory.FlowText(body,epilogue.text,25);
            }
            UiFactory.FlowText(body,"行动时段 "+view.tick+"  ·  你的承诺与已经完成的行动共同留下了这个结果。",23,UiFactory.Muted);
            UiFactory.Button("Review notes",body,"回顾这次旅程的笔记",()=>{CloseModal();ToggleDrawer("journal",true);});
            UiFactory.Button("Return title",body,"回到标题",()=>{CloseModal();ReturnToTitle();},true,56);
        }
        void QuitGame()
        {
            Confirm("离开余灯","已确认的进度会保留。未完成的交谈会停止。","退出",()=>
            {
                CancelTalk(); PlayerPrefs.Save();
#if UNITY_EDITOR
                UnityEditor.EditorApplication.isPlaying=false;
#else
                Application.Quit();
#endif
            });
        }
    }
}
