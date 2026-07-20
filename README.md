# NPC Director

面向 Unity 的 NPC 演出编排系统。Director 使用 OpenAI Agents SDK 按需调用剧情、Lore、
台词和演出 Specialist；确定性 Workflow 负责安全、权限、HITL、状态提交、回放、outbox
和 Unity 副作用。

## 当前状态

M0–M6 的代码与离线阶段门均已完成：

| 里程碑 | 已实现内容 | 验收状态 |
|---|---|---|
| M0 | Pydantic 单一契约源、动作/表情目录、Console/HTML 假引擎 | 离线通过 |
| M1 | 单 Agent baseline、golden baseline、自动 diff、系统指标 | 离线通过 |
| M2 | Director + 4 Specialists、Agents-as-tools、动态预算、Quest Negotiator Handoff | 离线通过 |
| M3 | SQLite 状态/Event/HITL/outbox、治理检查、限次 repair、两阶段提交 | 离线通过 |
| M4 | 36 条 Eval、5 组消融、judge 校准、回放、trace 转 regression | 离线通过 |
| M5 | FastAPI/WebSocket、Unity C# 客户端、白名单、TTS 接口、打断和重连去重 | 协议测试通过 |
| M6 | BM25 JIT RAG、权限 scope、缓存、上下文压缩、长期记忆、重试/降级、压力测试 | 离线通过 |

尚待用户配置后执行的只有真实 OpenAI 模型评测和 Unity Editor/Player 运行时联调。仓库内
recorded baseline 与离线压力数据用于验证评测和治理链路，不代表线上模型质量、成本或延迟。

## 核心边界

- 模型只输出 `TurnProposal` / `PerformanceDraft`；可信身份、真实调用链和 prompt 版本由
  Finalizer 写入 `PerformanceDirective.runtime_meta`。
- Director 默认通过 Agents-as-tools 保持控制权；只有任务条件或报酬谈判才 Handoff 给
  `Quest Negotiator`，每回合最多一次。
- 玩家输入是 user payload 中的不可信数据；命中 prompt injection 后不调用任何创作 Agent。
- Backend Domain State 是业务真源，不信任 Unity 上报的 world flags 或客户端角色核心。
- 状态建议仅在 Unity `performance.completed` 后提交；ACK 前 turn 保持 `ready_to_emit`。
- outbox 使用 at-least-once 投递；Unity 用持久化 idempotency key 去重已完成和执行中计划。
- Lore 在权限过滤后执行 BM25 JIT 检索，并受 top-k、token、字符和 TTL cache 预算约束。

## 安装

要求 Python 3.11+：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

项目不会自动读取 `.env`；需要把 `.env.example` 中的配置导出为环境变量。

## 离线验收

一键执行不需要 API Key 的阶段门：

```bash
source .venv/bin/activate
make verify
```

也可以单独执行：

```bash
make lint
make test
make demo
make catalog
make eval
make ablations
make judge-calibration
make load-test
```

输出位置：

- `artifacts/demo-session_1.html`：假引擎演出时间线。
- `eval/reports/latest.json`：36 条 recorded golden eval。
- `eval/reports/ablations.json`：single/main-sub/记忆/RAG 消融。
- `eval/reports/judge_calibration.json`：judge 与人工标签校准结果。
- `eval/reports/load_test.json`：确定性离线服务压力数据。

当前 recorded 结果：single baseline 和动态 Main-sub 均为 36/36；固定全调用仅 7/36，
无记忆版本为 33/36；全量 Lore 保持质量但平均 token 为动态 JIT RAG 的约 4.4 倍。
Judge 校准为 9/10。具体数值以报告文件为准。

## 真实模型

最少配置：

```bash
export OPENAI_API_KEY="..."
export NPC_DIRECTOR_MODEL="..."  # 留空则使用 Agents SDK 默认模型
```

可按角色分别配置模型：

```bash
export NPC_DIRECTOR_DIRECTOR_MODEL="..."
export NPC_DIRECTOR_NARRATIVE_MODEL="..."
export NPC_DIRECTOR_LORE_MODEL="..."
export NPC_DIRECTOR_SCREENWRITER_MODEL="..."
export NPC_DIRECTOR_PERFORMANCE_MODEL="..."
export NPC_DIRECTOR_FALLBACK_MODEL="..."
```

运行单 Agent baseline 与两种 live eval：

```bash
python -m scripts.run_turn data/examples/reunion_request.json --html
make eval-live
make eval-live-main-sub
```

如需估算成本，再设置：

```bash
export NPC_DIRECTOR_INPUT_COST_PER_MILLION="..."
export NPC_DIRECTOR_OUTPUT_COST_PER_MILLION="..."
```

## API 与 Unity

启动默认 Main-sub 服务：

```bash
python -m npc_director.api
```

- 健康检查：`GET http://127.0.0.1:8000/health`
- Unity WebSocket：`ws://127.0.0.1:8000/ws/{session_id}`
- 查询审批：`GET /approvals/{approval_id}`
- 处理审批：`POST /approvals/{approval_id}`，action 支持 `approve`、`reject`、`edit`

Unity 接入：

1. 把 `unity/NPCDirectorClient` 复制到 Unity 项目的 `Assets/`。
2. 按 `unity/NPCDirectorClient/README.md` 配置 `NPCDirectorClient`、
   `PerformanceExecutor`、动作目录、表情、凝视和可选 TTS 组件。
3. 将 endpoint 和 `sessionId` 保持一致，并由 UI 调用 `SendPlayerInput`。
4. 为 Animator 配置本地 `thinking` 过渡状态及白名单动作。

客户端会上报 `ack/started/completed/interrupted/error`。断线时消息保留在发送队列，重连后
后端重发未确认 outbox；`PerformanceExecutor` 使用 `PlayerPrefs` 持久化最近 256 个已完成
key，并识别执行中的重复计划，避免重复播放。

## Eval 与回放

主要命令：

```bash
# 指定 recorded 变体
python -m eval.runner --mode recorded --architecture main_sub \
  --baseline eval/baselines/main_sub_dynamic.jsonl

# 对已持久化回合重放治理逻辑
python -m scripts.replay_turn "session-1:1" --mode deterministic

# 使用同一状态、角色、记忆和 Lore 配置重新推理
python -m scripts.replay_turn "session-1:1" --mode reinfer

# 把坏 trace 追加为 regression 草稿
python -m scripts.trace_to_regression "session-1:1" \
  --output eval/cases/regressions.jsonl
```

Eval 的路由判定只信运行时 hooks 记录的 Specialist/Handoff trace，不信模型在
`plan.required_specialists` 中的自报信息。Schema、动作、状态权限和路由使用确定性 diff；
主观质量才使用校准后的 judge。

## 数据与配置

- `src/npc_director/contracts/`：Agent、治理、eval、API 和 Unity 的唯一契约源。
- `data/characters/`：服务端角色核心和风格，会覆盖客户端占位角色卡。
- `data/world/lore/`：支持 JSON/Markdown/TXT；目录和文档 scope 控制访问权限。
- `data/catalogs/performance_catalog.json`：由契约枚举导出，修改白名单后运行 `make catalog`。
- `data/runtime/npc_director.db`：默认 SQLite 业务状态、回合、审批、事件、outbox 和长期记忆。
- `.env.example`：模型路由、超时、预算、RAG、并发、重试和存储配置。

状态 flag 使用 `[{"name": ..., "value": ...}]`，以满足 OpenAI strict structured output；
治理层提交时再转换为领域状态 patch。
