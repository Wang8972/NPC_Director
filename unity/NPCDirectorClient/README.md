# NPC Director Unity Client

把 `NPCDirectorClient` 目录复制到 Unity 项目的 `Assets/` 下，场景中创建：

1. `NPCDirectorClient`：配置 `ws://127.0.0.1:8000/ws/{sessionId}`。
2. `PerformanceExecutor`：绑定 Animator、字幕、表情和凝视组件。
3. `ActionCatalog`：只登记允许的动作；默认至少配置 idle、nod、shake_head、
   step_forward、point。
4. `FacialPresetController`：配置 neutral、happy、sad、angry、surprised。

客户端采用 at-least-once 消息传递：后端在 Unity 回传 `performance.ack` 前可能重发，
`PerformanceExecutor` 按 `idempotency_key` 去重已完成和执行中的计划，保证不会重复播放。
后端只在 `performance.completed` 后提交状态；Unity 必须在接受、开始、完成、打断或失败时
分别上报对应事件。

接入后至少验证：连续 10 回合、主动打断、连接中断后恢复、Unity 进程重启后重复计划、
关键剧情审批和错误消息回到 idle。WebGL 不支持 `ClientWebSocket`，需替换为平台 WebSocket
适配器。
