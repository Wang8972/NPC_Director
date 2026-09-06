using System;
using System.Text;
using UnityEngine;
using UnityEngine.UI;

namespace NPCDirector
{
    public class PrototypeP2GameController : MonoBehaviour
    {
        [SerializeField] private PrototypeP2Client client;
        [SerializeField] private PrototypeSceneStateController sceneStateController;
        [SerializeField] private Text connectionText;
        [SerializeField] private Text objectiveText;
        [SerializeField] private Text selectedNpcText;
        [SerializeField] private Text routeText;
        [SerializeField] private Text feedbackText;
        [SerializeField] private Text clueText;
        [SerializeField] private Text stateText;

        private string selectedNpcId = "mechanic_lia";
        private bool busy;

        public string SelectedNpcId => selectedNpcId;
        public bool IsBusy => busy;

        public void Configure(
            PrototypeP2Client configuredClient,
            PrototypeSceneStateController sceneState,
            Text connection,
            Text objective,
            Text selectedNpc,
            Text route,
            Text feedback,
            Text clues,
            Text state)
        {
            client = configuredClient;
            sceneStateController = sceneState;
            connectionText = connection;
            objectiveText = objective;
            selectedNpcText = selectedNpc;
            routeText = route;
            feedbackText = feedback;
            clueText = clues;
            stateText = state;
            sceneStateController?.BeginSession(client.SessionId);
            RefreshSelection();
        }

        public void SelectNpc(string npcId)
        {
            selectedNpcId = npcId;
            RefreshSelection();
            SetFeedback($"已选择 {DisplayName(npcId)}");
        }

        public void Observe(string objectId)
        {
            if (busy)
            {
                SetFeedback("当前动作尚未结束；请等待 completed 或先执行中断。");
                return;
            }
            client.Observe(objectId);
        }

        public void ExecuteCommand(string command)
        {
            if (command.StartsWith("select:", StringComparison.Ordinal))
            {
                SelectNpc(command.Substring("select:".Length));
                return;
            }
            if (command == "reset")
            {
                client.ResetPrototype();
                return;
            }
            if (command == "interrupt")
            {
                client.InterruptCurrent();
                return;
            }
            if (busy)
            {
                SetFeedback("输入已锁定：当前计划必须先到达终态。");
                return;
            }
            if (command.StartsWith("fixture:", StringComparison.Ordinal))
            {
                client.SendFixture(selectedNpcId, command);
                return;
            }
            SetFeedback($"未知 P2 命令：{command}");
        }

        public void ApplySnapshot(PrototypeStateSnapshotPayload snapshot)
        {
            sceneStateController?.ApplySnapshot(snapshot);
            bool hasPendingAction = snapshot.pending_action != null &&
                                    !string.IsNullOrWhiteSpace(snapshot.pending_action.action_id);
            busy = hasPendingAction;
            if (objectiveText != null)
            {
                objectiveText.text = $"目标：{snapshot.objective_state}";
            }
            if (routeText != null)
            {
                routeText.text = $"路线：{snapshot.route_flags?.fuse_route ?? "none"}";
            }
            if (clueText != null)
            {
                StringBuilder clues = new StringBuilder("已发现事实：");
                foreach (string factId in snapshot.discovered_fact_ids ?? Array.Empty<string>())
                {
                    clues.Append("\n• ").Append(factId);
                }
                clueText.text = clues.ToString();
            }
            if (stateText != null)
            {
                string pending = hasPendingAction
                    ? $"{snapshot.pending_action.action_type}/{snapshot.pending_action.actor_id}"
                    : "none";
                stateText.text =
                    $"world_version={snapshot.world_version}\n" +
                    $"pending={pending}\n" +
                    $"input_locked={busy}";
            }
            if (snapshot.objective_state == "prototype_success")
            {
                SetFeedback("Prototype Success：后端快照确认闸门已恢复。");
            }
        }

        public void ApplyWorldEvent(WorldEventPayload worldEvent)
        {
            if (worldEvent.event_type == "session_reset")
            {
                sceneStateController?.BeginSession(worldEvent.session_id);
            }
            SetFeedback($"[{worldEvent.event_type}] {worldEvent.summary}");
            Debug.Log(
                $"[P2_WORLD_EVENT] type={worldEvent.event_type} " +
                $"version={worldEvent.world_version} facts=" +
                string.Join(",", worldEvent.revealed_fact_ids ?? Array.Empty<string>()));
        }

        public void SetBusy(bool value, string detail)
        {
            busy = value;
            SetFeedback(detail);
        }

        public void SetConnectionState(string value)
        {
            if (connectionText != null)
            {
                connectionText.text = $"连接：{value}";
            }
        }

        private void SetFeedback(string value)
        {
            if (feedbackText != null)
            {
                feedbackText.text = $"反馈：{value}";
            }
        }

        private void RefreshSelection()
        {
            if (selectedNpcText != null)
            {
                selectedNpcText.text = $"当前 NPC：{DisplayName(selectedNpcId)} ({selectedNpcId})";
            }
        }

        private static string DisplayName(string npcId)
        {
            switch (npcId)
            {
                case "guard_captain_maren":
                    return "玛伦";
                case "mechanic_lia":
                    return "莉娅";
                case "porter_finn":
                    return "费恩";
                default:
                    return npcId;
            }
        }
    }
}
