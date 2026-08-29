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
    public sealed class PrototypeP2Client : MonoBehaviour
    {
        [SerializeField] private string endpoint = "ws://127.0.0.1:8766";
        [SerializeField] private string sessionId = "p2-fake-001";
        [SerializeField] private NpcRegistry npcRegistry;
        [SerializeField] private PrototypeSceneActionExecutor sceneActionExecutor;
        [SerializeField] private PrototypeP2GameController gameController;

        private readonly ConcurrentQueue<Action> mainThreadActions =
            new ConcurrentQueue<Action>();
        private readonly ConcurrentQueue<string> outgoingMessages =
            new ConcurrentQueue<string>();
        private readonly SemaphoreSlim sendLock = new SemaphoreSlim(1, 1);
        private CancellationTokenSource cancellation;
        private ClientWebSocket socket;
        private int latestWorldVersion;

        public string SessionId => sessionId;
        public bool IsConnected => socket != null && socket.State == WebSocketState.Open;

        public void Configure(
            string configuredEndpoint,
            string configuredSessionId,
            NpcRegistry registry,
            PrototypeSceneActionExecutor actionExecutor,
            PrototypeP2GameController controller)
        {
            endpoint = configuredEndpoint;
            sessionId = configuredSessionId;
            npcRegistry = registry;
            sceneActionExecutor = actionExecutor;
            gameController = controller;
        }

        private async void Start()
        {
            cancellation = new CancellationTokenSource();
            await ConnectLoopAsync(cancellation.Token);
        }

        private async void OnDisable()
        {
            cancellation?.Cancel();
            if (socket == null)
            {
                return;
            }
            try
            {
                await socket.CloseAsync(
                    WebSocketCloseStatus.NormalClosure,
                    "P2 client disabled",
                    CancellationToken.None);
            }
            catch (WebSocketException)
            {
            }
            socket.Dispose();
            socket = null;
        }

        private void Update()
        {
            while (mainThreadActions.TryDequeue(out Action action))
            {
                action.Invoke();
            }
        }

        public void SendFixture(string npcId, string fixtureId)
        {
            string turnId = $"{sessionId}:{Guid.NewGuid():N}";
            TurnRequestEnvelope request = new TurnRequestEnvelope
            {
                message_id = $"request:{turnId}",
                payload = new TurnRequestPayload
                {
                    session_id = sessionId,
                    turn_id = turnId,
                    npc_id = npcId,
                    player_input = fixtureId,
                    character_core = "P2 Fake fixture; backend profile is authoritative.",
                    scene = new SceneSnapshot { location = "prototype_gate_repair" }
                }
            };
            gameController?.SetBusy(true, $"发送 {fixtureId}");
            QueueMessage(JsonUtility.ToJson(request));
        }

        public void Observe(string objectId)
        {
            string requestId = $"{sessionId}:observe:{Guid.NewGuid():N}";
            SceneObserveRequestEnvelope request = new SceneObserveRequestEnvelope
            {
                message_id = $"observe:{requestId}",
                payload = new SceneObserveRequestPayload
                {
                    session_id = sessionId,
                    request_id = requestId,
                    object_id = objectId,
                    expected_world_version = latestWorldVersion
                }
            };
            gameController?.SetBusy(true, $"观察 {objectId}");
            QueueMessage(JsonUtility.ToJson(request));
        }

        public void ResetPrototype()
        {
            string token = $"p2-reset:{Guid.NewGuid():N}";
            PrototypeResetRequestEnvelope request = new PrototypeResetRequestEnvelope
            {
                message_id = $"reset:{token}",
                payload = new PrototypeResetRequestPayload
                {
                    session_id = sessionId,
                    reset_token = token
                }
            };
            gameController?.SetBusy(true, "请求后端重置");
            QueueMessage(JsonUtility.ToJson(request));
        }

        public void InterruptCurrent()
        {
            sceneActionExecutor?.InterruptCurrent("manual_p2_test");
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
                    gameController?.SetConnectionState("连接中");
                    await socket.ConnectAsync(new Uri(endpoint), token);
                    retry = 0;
                    mainThreadActions.Enqueue(() => gameController?.SetConnectionState("已连接 Fake"));
                    await FlushOutgoingAsync(token);
                    await ReceiveLoopAsync(token);
                }
                catch (Exception error) when (!token.IsCancellationRequested)
                {
                    retry += 1;
                    mainThreadActions.Enqueue(
                        () => gameController?.SetConnectionState($"重连中：{error.GetType().Name}"));
                    int delayMs = Math.Min(30000, 500 * (1 << Math.Min(retry, 6)));
                    await Task.Delay(delayMs, token);
                }
            }
        }

        private async Task ReceiveLoopAsync(CancellationToken token)
        {
            byte[] buffer = new byte[8192];
            while (socket != null && socket.State == WebSocketState.Open &&
                   !token.IsCancellationRequested)
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
                    HandleIncoming(Encoding.UTF8.GetString(stream.ToArray()));
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
                    gameController?.SetBusy(false, error?.payload?.message ?? "未知错误");
                    Debug.LogWarning(
                        $"[P2_ERROR] code={error?.payload?.code} message={error?.payload?.message}");
                });
                return;
            }
            if (header.type == "state.snapshot")
            {
                StateSnapshotEnvelope snapshot = JsonUtility.FromJson<StateSnapshotEnvelope>(json);
                if (snapshot?.payload == null || snapshot.payload.session_id != sessionId)
                {
                    return;
                }
                mainThreadActions.Enqueue(() =>
                {
                    latestWorldVersion = snapshot.payload.world_version;
                    gameController?.ApplySnapshot(snapshot.payload);
                });
                return;
            }
            if (header.type == "world.event")
            {
                WorldEventEnvelope worldEvent = JsonUtility.FromJson<WorldEventEnvelope>(json);
                if (worldEvent?.payload == null || worldEvent.payload.session_id != sessionId)
                {
                    return;
                }
                mainThreadActions.Enqueue(() => gameController?.ApplyWorldEvent(worldEvent.payload));
                return;
            }
            if (header.type == "performance.plan")
            {
                PerformancePlanEnvelope plan = JsonUtility.FromJson<PerformancePlanEnvelope>(json);
                mainThreadActions.Enqueue(() => ExecutePerformance(plan));
                return;
            }
            if (header.type == "scene.action.plan")
            {
                SceneActionPlanEnvelope plan = JsonUtility.FromJson<SceneActionPlanEnvelope>(json);
                mainThreadActions.Enqueue(() => ExecuteSceneAction(plan));
            }
        }

        private void ExecutePerformance(PerformancePlanEnvelope plan)
        {
            if (plan?.payload?.directive == null ||
                plan.payload.directive.schema_version != "1.0" ||
                plan.payload.directive.session_id != sessionId ||
                !npcRegistry.TryResolve(plan.payload.directive.npc_id, out PerformanceExecutor executor))
            {
                ReportPerformanceEvent("error", plan?.payload, "invalid performance plan");
                return;
            }
            gameController?.SetBusy(true, $"{plan.payload.directive.npc_id} 回应中");
            bool accepted = executor.TryExecute(
                plan.payload,
                (eventType, turnId, key, detail) =>
                {
                    ReportPerformanceEvent(eventType, plan.payload, detail);
                    if (eventType == "completed" || eventType == "interrupted" ||
                        eventType == "error")
                    {
                        gameController?.SetBusy(false, $"回应 {eventType}");
                    }
                });
            if (!accepted)
            {
                ReportPerformanceEvent("error", plan.payload, "performance rejected locally");
                gameController?.SetBusy(false, "演出计划被本地拒绝");
            }
        }

        private void ExecuteSceneAction(SceneActionPlanEnvelope plan)
        {
            if (plan?.payload?.action == null)
            {
                return;
            }
            gameController?.SetBusy(true, $"执行 {plan.payload.action.action_type}");
            sceneActionExecutor.TryExecute(plan.payload, ReportSceneActionEvent);
        }

        private void ReportPerformanceEvent(
            string eventType,
            PerformancePlanPayload plan,
            string detail)
        {
            if (plan?.directive == null)
            {
                return;
            }
            PerformanceEventEnvelope message = new PerformanceEventEnvelope
            {
                message_id = $"event:{Guid.NewGuid():N}",
                type = $"performance.{eventType}",
                payload = new PerformanceEventPayload
                {
                    session_id = sessionId,
                    turn_id = plan.directive.turn_id,
                    idempotency_key = plan.idempotency_key,
                    event_type = eventType,
                    detail = detail,
                    occurred_at = DateTime.UtcNow.ToString("O")
                }
            };
            QueueMessage(JsonUtility.ToJson(message));
        }

        private void ReportSceneActionEvent(
            string eventType,
            SceneActionPlanPayload plan,
            string detail)
        {
            SceneActionEventEnvelope message = new SceneActionEventEnvelope
            {
                message_id = $"scene-event:{Guid.NewGuid():N}",
                type = $"scene.action.{eventType}",
                payload = new SceneActionEventPayload
                {
                    session_id = sessionId,
                    turn_id = plan.action.turn_id,
                    action_id = plan.action.action_id,
                    idempotency_key = plan.idempotency_key,
                    event_type = eventType,
                    detail = detail,
                    occurred_at = DateTime.UtcNow.ToString("O")
                }
            };
            QueueMessage(JsonUtility.ToJson(message));
            if (eventType == "completed" || eventType == "interrupted" || eventType == "error")
            {
                gameController?.SetBusy(false, $"场景动作 {eventType}");
            }
        }

        private void QueueMessage(string json)
        {
            outgoingMessages.Enqueue(json);
            _ = FlushOutgoingAsync(
                cancellation != null ? cancellation.Token : CancellationToken.None);
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
    }
}
