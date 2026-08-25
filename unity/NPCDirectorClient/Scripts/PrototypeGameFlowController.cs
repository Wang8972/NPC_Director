using System;
using UnityEngine;
using UnityEngine.UI;

namespace NPCDirector
{
    public sealed class PrototypeGameFlowController : MonoBehaviour
    {
        [SerializeField] private PrototypeSceneStateController sceneStateController;
        [SerializeField] private Text objectiveText;
        [SerializeField] private Text selectedNpcText;
        [SerializeField] private Text routeText;
        [SerializeField] private Text clueText;
        [SerializeField] private Text feedbackText;
        [SerializeField] private Text stateText;

        private PrototypeWorldState state;
        private string selectedNpcId = "";
        private int sessionSequence;

        public PrototypeWorldState State => state;
        public string SelectedNpcId => selectedNpcId;

        public void Configure(
            PrototypeSceneStateController stateController,
            Text objective,
            Text selectedNpc,
            Text route,
            Text clues,
            Text feedback,
            Text stateDebug)
        {
            sceneStateController = stateController;
            objectiveText = objective;
            selectedNpcText = selectedNpc;
            routeText = route;
            clueText = clues;
            feedbackText = feedback;
            stateText = stateDebug;
        }

        private void Start()
        {
            ResetPrototype();
        }

        public void ExecuteUiCommand(string command)
        {
            if (string.IsNullOrWhiteSpace(command))
            {
                return;
            }
            if (command.StartsWith("select:", StringComparison.Ordinal))
            {
                SelectNpc(command.Substring("select:".Length));
                return;
            }
            if (command == "reset")
            {
                ResetPrototype();
                return;
            }
            if (command == "self_check")
            {
                PrototypeP1GateRunner runner = FindObjectOfType<PrototypeP1GateRunner>();
                if (runner == null)
                {
                    SetFeedback("[error_missing_runner] 场景中缺少 P1 自动验收器。");
                    return;
                }
                runner.RunGate();
                SetFeedback("自动验收已运行，请在 Console 查看 [P1_SUMMARY]。");
                return;
            }
            ApplyAction(command);
        }

        public void SelectNpc(string npcId)
        {
            if (!PrototypePuzzleRules.IsCanonicalNpc(npcId))
            {
                SetFeedback($"[error_unknown_actor] 未知 NPC：{npcId}");
                return;
            }
            selectedNpcId = npcId;
            SetFeedback($"已选择 {NpcLabel(npcId)}。点击热点或使用调解按钮继续。");
            RefreshUi();
            Debug.Log($"[P1_SELECT] npc_id={npcId}");
        }

        public void HandleHotspot(string objectId)
        {
            if (state == null)
            {
                ResetPrototype();
            }

            switch (objectId)
            {
                case "gate_console":
                    ApplyAction(PrototypePuzzleRules.ObserveGateConsole);
                    break;
                case "generator":
                    ApplyAction(
                        state.FuseLocation == PrototypePuzzleRules.LiaId
                            ? PrototypePuzzleRules.InstallFuse
                            : PrototypePuzzleRules.InspectGenerator);
                    break;
                case "control_cabinet":
                    ApplyAction(
                        state.ControlCabinetAuthorized
                            ? PrototypePuzzleRules.RestartGate
                            : PrototypePuzzleRules.AuthorizeRestart);
                    break;
                case "cargo_crate_c12":
                    ApplyAction(
                        selectedNpcId == PrototypePuzzleRules.FinnId
                            ? PrototypePuzzleRules.GiveFuse
                            : PrototypePuzzleRules.ObserveCrate);
                    break;
                case "manifest_board":
                    ApplyAction(PrototypePuzzleRules.ObserveManifest);
                    break;
                case "alarm_lamp":
                    ApplyAction(PrototypePuzzleRules.ObserveAlarm);
                    break;
                default:
                    SetFeedback($"[error_unknown_object] 未知热点：{objectId}");
                    break;
            }
        }

        [ContextMenu("Reset P1 Prototype")]
        public void ResetPrototype()
        {
            sessionSequence += 1;
            selectedNpcId = "";
            state = new PrototypeWorldState($"p1-local-{sessionSequence}");
            if (sceneStateController != null)
            {
                sceneStateController.BeginSession(state.SessionId);
                sceneStateController.ApplySnapshot(state.ToSnapshot());
            }
            SetFeedback("原型已复位。先点击 gate_console 观察 E-17。");
            RefreshUi();
            Debug.Log(
                $"[P1_RESET] session={state.SessionId} hash={state.StableStateHash()}");
        }

        private void ApplyAction(string actionId)
        {
            if (state == null)
            {
                ResetPrototype();
            }
            PrototypeActionResult result = PrototypePuzzleRules.Apply(
                state,
                actionId,
                selectedNpcId);
            if (result.Changed && sceneStateController != null)
            {
                sceneStateController.ApplySnapshot(state.ToSnapshot());
            }
            SetFeedback($"[{result.Code}] {result.Message}");
            RefreshUi();
            Debug.Log(
                $"[P1_ACTION] action={actionId} actor={selectedNpcId} " +
                $"accepted={result.Accepted} changed={result.Changed} " +
                $"version={state.WorldVersion} objective={state.ObjectiveState} " +
                $"route={state.FuseRoute} code={result.Code}");
        }

        private void RefreshUi()
        {
            if (state == null)
            {
                return;
            }
            SetText(objectiveText, $"目标：{ObjectiveLabel(state)}");
            SetText(
                selectedNpcText,
                string.IsNullOrEmpty(selectedNpcId)
                    ? "当前 NPC：未选择"
                    : $"当前 NPC：{NpcLabel(selectedNpcId)}");
            SetText(routeText, $"路线：{RouteLabel(state.FuseRoute)}");
            string[] facts = state.SortedPlayerFacts();
            SetText(
                clueText,
                facts.Length == 0
                    ? "线索：无"
                    : "线索：\n• " + string.Join("\n• ", facts));
            SetText(
                stateText,
                $"session={state.SessionId}\n" +
                $"world_version={state.WorldVersion}\n" +
                $"fuse_location={state.FuseLocation}\n" +
                $"crate_authorized={state.CrateAuthorized}\n" +
                $"cabinet_authorized={state.ControlCabinetAuthorized}\n" +
                $"state_hash={state.StableStateHash().Substring(0, 12)}");
        }

        private void SetFeedback(string message)
        {
            SetText(feedbackText, $"反馈 / 字幕：{message}");
        }

        private static void SetText(Text target, string value)
        {
            if (target != null)
            {
                target.text = value;
            }
        }

        private static string NpcLabel(string npcId)
        {
            switch (npcId)
            {
                case PrototypePuzzleRules.MarenId:
                    return "玛伦（程序 / 追责）";
                case PrototypePuzzleRules.LiaId:
                    return "莉娅（安全 / 维修）";
                case PrototypePuzzleRules.FinnId:
                    return "费恩（自保 / 现场安全）";
                default:
                    return npcId;
            }
        }

        private static string RouteLabel(string route)
        {
            switch (route)
            {
                case "cooperation":
                    return "合作";
                case "procedure":
                    return "程序";
                default:
                    return "未选择";
            }
        }

        private static string ObjectiveLabel(PrototypeWorldState currentState)
        {
            switch (currentState.ObjectiveState)
            {
                case "investigate_fault":
                    return currentState.PlayerKnows("fact_console_e17")
                        ? "选择莉娅，点击发电机完成诊断"
                        : "观察控制台并确认故障";
                case "find_fuse":
                    return "通过合作或程序路线取得保险丝";
                case "install_fuse":
                    return "选择莉娅，点击发电机安装保险丝";
                case "restart_gate":
                    return "选择玛伦，两次点击控制柜完成授权与重启";
                case PrototypeWorldState.SuccessObjective:
                    return "Prototype Success";
                default:
                    return currentState.ObjectiveState;
            }
        }
    }
}
