using System;
using System.Collections.Concurrent;
using System.IO;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace NPCDirector
{
    public sealed class NPCDirectorClient : MonoBehaviour
    {
        [SerializeField] private string endpoint = "ws://127.0.0.1:8000/ws/session-1";
        [SerializeField] private string sessionId = "session-1";
        [SerializeField] private string npcId = "elder_maren";
        [SerializeField] private PerformanceExecutor executor;
        [SerializeField] private Animator animator;
        [SerializeField] private string thinkingState = "thinking";
        [SerializeField] private string idleState = "idle";

        private readonly ConcurrentQueue<Action> mainThreadActions = new ConcurrentQueue<Action>();
        private readonly ConcurrentQueue<string> outgoingMessages = new ConcurrentQueue<string>();
        private readonly SemaphoreSlim sendLock = new SemaphoreSlim(1, 1);
        private CancellationTokenSource cancellation;
        private ClientWebSocket socket;
        private int turnIndex;

        private async void OnEnable()
        {
            cancellation = new CancellationTokenSource();
            await ConnectLoopAsync(cancellation.Token);
        }

        private async void OnDisable()
        {
            cancellation?.Cancel();
            if (socket != null)
            {
                try
                {
                    await socket.CloseAsync(
                        WebSocketCloseStatus.NormalClosure,
                        "client disabled",
                        CancellationToken.None);
                }
                catch (WebSocketException)
                {
                }
                socket.Dispose();
                socket = null;
            }
        }

        private void Update()
        {
            while (mainThreadActions.TryDequeue(out Action action))
            {
                action.Invoke();
            }
        }

        public void SendPlayerInput(string playerInput)
        {
            turnIndex += 1;
            string turnId = $"{sessionId}:{turnIndex}";
            TurnRequestEnvelope message = new TurnRequestEnvelope
            {
                message_id = $"request:{turnId}",
                payload = new TurnRequestPayload
                {
                    session_id = sessionId,
                    turn_id = turnId,
                    npc_id = npcId,
                    player_input = playerInput,
                    character_core = "由后端角色库覆盖的客户端占位信息",
                    scene = new SceneSnapshot
                    {
                        location = gameObject.scene.name,
                        animator_state = animator != null
                            ? animator.GetCurrentAnimatorStateInfo(0).shortNameHash.ToString()
                            : "idle"
                    }
                }
            };
            PlayThinkingState();
            QueueMessage(JsonUtility.ToJson(message));
        }

        private async Task ConnectLoopAsync(CancellationToken token)
        {
            int retry = 0;
            while (!token.IsCancellationRequested)
            {
                try
                {
                    socket?.Dispose();
                    socket = new ClientWebSocket();
                    await socket.ConnectAsync(new Uri(endpoint), token);
                    retry = 0;
                    await FlushOutgoingAsync(token);
                    await ReceiveLoopAsync(token);
                }
                catch (Exception) when (!token.IsCancellationRequested)
                {
                    retry += 1;
                    int delayMs = Math.Min(30000, 500 * (1 << Math.Min(retry, 6)));
                    await Task.Delay(delayMs, token);
                }
            }
        }

        private async Task ReceiveLoopAsync(CancellationToken token)
        {
            byte[] buffer = new byte[8192];
            while (socket != null && socket.State == WebSocketState.Open && !token.IsCancellationRequested)
            {
                using (MemoryStream stream = new MemoryStream())
                {
                    WebSocketReceiveResult result;
                    do
                    {
                        result = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), token);
                        if (result.MessageType == WebSocketMessageType.Close)
                        {
                            return;
                        }
                        stream.Write(buffer, 0, result.Count);
                    }
                    while (!result.EndOfMessage);

                    string json = Encoding.UTF8.GetString(stream.ToArray());
                    HandleIncoming(json);
                }
            }
        }

        private void HandleIncoming(string json)
        {
            MessageHeader header = JsonUtility.FromJson<MessageHeader>(json);
            if (header == null)
            {
                return;
            }
            if (header.type == "error")
            {
                ErrorEnvelope error = JsonUtility.FromJson<ErrorEnvelope>(json);
                mainThreadActions.Enqueue(() =>
                {
                    if (animator != null && !string.IsNullOrWhiteSpace(idleState))
                    {
                        animator.CrossFade(idleState, 0.15f);
                    }
                    Debug.LogWarning(
                        $"NPC Director error [{error?.payload?.code}]: {error?.payload?.message}");
                });
                return;
            }
            if (header.type != "performance.plan")
            {
                return;
            }
            PerformancePlanEnvelope plan = JsonUtility.FromJson<PerformancePlanEnvelope>(json);
            if (plan == null || plan.payload == null || plan.payload.directive == null)
            {
                return;
            }
            if (plan.payload.directive.schema_version != "1.0" ||
                plan.payload.directive.session_id != sessionId ||
                plan.payload.directive.npc_id != npcId)
            {
                ReportEvent(
                    "error",
                    plan.payload.directive.turn_id,
                    plan.payload.idempotency_key,
                    "directive identity or schema mismatch");
                return;
            }
            mainThreadActions.Enqueue(() =>
            {
                bool accepted = executor != null && executor.TryExecute(plan.payload, ReportEvent);
                if (!accepted)
                {
                    ReportEvent(
                        "error",
                        plan.payload.directive.turn_id,
                        plan.payload.idempotency_key,
                        "plan rejected locally");
                }
            });
        }

        private void ReportEvent(
            string eventType,
            string turnId,
            string idempotencyKey,
            string detail)
        {
            PerformanceEventEnvelope message = new PerformanceEventEnvelope
            {
                message_id = $"event:{Guid.NewGuid():N}",
                type = $"performance.{eventType}",
                payload = new PerformanceEventPayload
                {
                    session_id = sessionId,
                    turn_id = turnId,
                    idempotency_key = idempotencyKey,
                    event_type = eventType,
                    detail = detail,
                    occurred_at = DateTime.UtcNow.ToString("O")
                }
            };
            QueueMessage(JsonUtility.ToJson(message));
        }

        private void QueueMessage(string json)
        {
            outgoingMessages.Enqueue(json);
            _ = FlushOutgoingAsync(cancellation != null ? cancellation.Token : CancellationToken.None);
        }

        private async Task FlushOutgoingAsync(CancellationToken token)
        {
            await sendLock.WaitAsync(token);
            try
            {
                while (socket != null && socket.State == WebSocketState.Open &&
                       outgoingMessages.TryDequeue(out string json))
                {
                    try
                    {
                        byte[] payload = Encoding.UTF8.GetBytes(json);
                        await socket.SendAsync(
                            new ArraySegment<byte>(payload),
                            WebSocketMessageType.Text,
                            true,
                            token);
                    }
                    catch
                    {
                        outgoingMessages.Enqueue(json);
                        throw;
                    }
                }
            }
            finally
            {
                sendLock.Release();
            }
        }

        private void PlayThinkingState()
        {
            if (animator != null && !string.IsNullOrWhiteSpace(thinkingState))
            {
                animator.CrossFade(thinkingState, 0.15f);
            }
        }

    }
}
