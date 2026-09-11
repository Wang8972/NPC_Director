# NPC Director v2 接入

`backend/last_light/director.py` 使用随包 NPC Director 的真实 `build_default_service()`，并把同一计量模型 transport 注入 `BoundedDirectorExecutor`。Director/Planner、按需协作与谈判、Writer、Performance、Quality、episode、知识和长期记忆都经过生产链。`rehearsal` 是明确标注的作者排练，不会调用这个模型链，也不会在模型失败时静默顶替它。

## API

```python
bridge = DirectorBridge(data_dir, engine_lookup, persist)
bridge.available()                         # available/model/source/error/token_budget
await bridge.start(sid, npc_id, text, audience)  # 返回立即可轮询的 TalkJob
bridge.get_job(sid, job_id)
await bridge.acknowledge(sid, job_id, line_id)
await bridge.cancel(sid, job_id)
await bridge.sync_world(sid)
bridge.get_active_job(sid)                  # TalkJob 或 None
bridge.has_active_job(sid)
await bridge.checkpoint(sid, destination)   # 单局 SQLite 快照
await bridge.restore_checkpoint(sid, source)
await bridge.close()
```

`engine_lookup(sid)` 返回权威 `WorldEngine`，`persist(sid)` 是同步持久化回调。参数错误抛出 `ValueError`；依赖/凭据未就绪抛出 `DirectorUnavailable`。模型生成的失败保存为 job 的 `failed/error`，不泄露 provider 返回体或凭据。

`TalkJob.lines` 是累积数组。每行 `id` 稳定，Unity 去重后显示完整文本，再逐行 ACK。ACK 提交已听见的社会行为和 v2 发言完成事务，下一名 NPC 的推理在独立 asyncio task 中继续；HTTP 不等待下一次模型调用。重复 ACK 幂等。取消未显示的行使用 interrupted，不伪造 completed；已经完成的台词与承诺保留。

`status` 为 `running/waiting_delivery/completed/failed/cancelled`。交谈完成不表示检修、搬运或救援任务完成。`suggested_steps` 在对应台词 ACK 后出现，仍必须由玩家确认并经 WorldEngine 的 propose/begin/complete 校验和执行。不得自动点击或自动执行建议。

根 API 应在 `has_active_job(sid)` 时禁止推进世界、改变角色可听范围或恢复存档；阅读界面可以继续。新玩家发言会取消前一个未完成 job。每一拍生成与交付都校验世界 revision，旧结果不能应用到变化后的世界。`sync_world` 仅投影本角色可知事实；显著行动事件可以合并成一个前台 `world_event` job，根 `/complete` 返回它供 UI 正常轮询。普通查看和移动不会自动请求模型。

## 三个边界

1. **物理真源**：WorldEngine。Director 不写物品、设备、烟气、位置或伤情。模型只提出 TrainMeaning；社会接受也只通过 `apply_decision`。`accept_task`、`loan`、`child_delegation` 等仍由当前守卫决定是否成立。
2. **认知与来源**：每个角色只接收自己的 `npc_context`。四份角色文件的私密背景只进入本人完整 profile，其他人只见公开名册。玩家材料列表不会全部注入 NPC；输入接入器只选择玩家本次实际出示的材料，规则核验来源后才授予知情。NPC 消息必须等真实发言送达，后继咨询才运行。
3. **语义接入**：生产 v2 先理解与生成；额外的 TrainMeaning 节点把已生成台词中的社会行为及未来计划映射成游戏 ID。每个社会决定必须附台词逐字引文；不存在的动作、对象、参与者、他人的私有事实、替别人接受任务均拒绝。它不能另写故事或替代 v2。可执行条件由规则核验，角色是否愿意在有效条件下合作仍由 AI 按动机、历史与交涉决定。

通用 v2 的世界状态写权限在本游戏的场景策略中被关闭，仅允许内部关系变化。游戏物理动作完成与 `performance.completed` 完全分开。v2 的已审核生成内容可用于求援电文、广播、人物交流及可选邀请；不能修改事故真相、生成新出口或创造救援资源。

## 数据和恢复

传给 bridge 的 `data_dir` 下：

```text
director/<session_id>/service.sqlite   v2 所有状态、知识、记忆、outbox + ll_jobs/ll_groundings/ll_meta
director/usage.sqlite                  全局调用和 token 账本，永不随游戏存档回滚
```

SQLite 为每次操作建立连接，快照使用 SQLite backup，不复制活动 WAL。根保存时必须把世界快照与 `checkpoint` 结果成对保存；有活动 job 时拒绝保存。恢复先取消当前对话，再恢复同局数据库并清理 service 缓存。其他 session 不受影响。

社会决定有稳定 `decision_id`，WorldEngine 持久去重；台词有稳定 `line_id`。完成意图与 world-applied 阶段写入桥日志，用于恢复丢失的 ACK 响应。网络失败或进程重启不能把未显示的行当作已说出。中断生成会明确失败，不能用预写台词冒充模型结果。

## 模型配置和成本

默认模型固定为 `qwen3.8-flash`，所有 v2 节点、审核、输入接入和动作语义接入都使用同一模型。没有自动升级或昂贵 fallback。

```text
LAST_LIGHT_MODEL=qwen3.8-flash
LAST_LIGHT_API_KEY=<在后端环境配置，不写入Unity>
LAST_LIGHT_BASE_URL=<OpenAI兼容地址>
LAST_LIGHT_API=chat_completions          # 或 responses
LAST_LIGHT_REASONING=none               # 已验证Qwen支持；避免隐藏推理占满输出上限
LAST_LIGHT_TOKEN_BUDGET=1000000          # 正式游玩可配置上限；验收脚本独立固定200000
```

也支持已存在的 `OPENAI_API_KEY` / `OPENAI_BASE_URL`。仅显式设置 `LAST_LIGHT_USE_CODEX_AUTH=1` 时，才在本机后端内存中复用当前 Codex provider 的凭据；要求 HTTPS，显式 endpoint 与凭据所属 endpoint 不同会拒绝。不会修改 Codex 配置，也不会把密钥写入存档、日志或 Unity。

transport 对每一次网络请求预留 token，供应商报告 usage 后按实记账；超时、取消或缺失 usage 按预留量保守计费。输出有硬上限，网络重试关闭；v2 的局部修复同样经过总账本。游戏动作语义节点还占用同一 episode 的调用和 token 预算。回滚游戏存档不退模型费用。

低成本协议使用提示中的 JSON schema 和本地 Pydantic 校验，不依赖所有服务实现原生约束解码。兼容性必须通过目标 provider 实测，不能把当前 recorded 结果称作 Qwen 质量结果。

正式运行保留v2默认的96,000 token单episode容量、6次NPC自主回合与180秒活动预算；它与整个验收总计200,000的限制不同。角色可见动作采用相关检索和前置依赖补充，压缩重复说明而不省略权限。已知事实被按来源和认知等级提供给内容审核策略，合法引用同步登记；未经核实的转述保持claim。

每局已有父目标 `last_light_rescue`，跨episode计划复用同一目标；物理完成仍由WorldEngine决定。已送达且正式发布的公开文书进入调查笔记，私密候选与审核意见不泄露。结局出现后只关闭目标，不再启动新一轮付费救援。

## 验证

依赖：Python 3.11+、Pydantic 2、OpenAI SDK、`openai-agents`，以及随包 `npc-director`（其 pyproject 安装其余依赖）；测试使用 pytest 与 pytest-asyncio。

不调用模型的测试：

```bash
PYTHONPATH=backend python -m pytest backend/tests/test_director_bridge.py -q
```

测试实际使用默认 v2 service、BoundedDirectorExecutor、完成事务和 SQLite，仅替换模型节点的返回；source 明确为 `recorded`。覆盖交付、幂等、取消、revision、防私密泄漏、多 NPC 咨询、存档隔离和 token 预算。recorded 不能评价自然度、人格或 Qwen 的实际能力。

只有得到明确 live 授权后才运行：

```bash
python tools/live_eval.py --live --only 2
```

总共六个场景，每个至多一次；兼容性探测本身就是第1个，后面只有五个功能场景。

出现具体故障并修复后，可用 `--retry-failed-once --only <ID>` 做最多一次定向复测；失败原记录留在earlier_attempts，账本不重置。这不是三次重复的统计评测。

| 编号 / `--only` ID | 检查内容 |
| --- | --- |
| 1 / `compatibility` | 一个短 JSON 协议探测；已有成功记录直接复用，不重新调用 |
| 2 / `stay_cooperation` | 留车方案中的林岚—陈默真实咨询，以及至少一项合法建议动作的实际提交 |
| 3 / `evacuation_dependencies` | 撤离方案的依赖关系与一批实际动作，交通、步道、出口分别核实 |
| 4 / `xu_renegotiation` | 通过真实等待、借出和接入造成需求变化、借约失效，再由真实AI重新协商 |
| 5 / `fulfilled_commitment_privacy` | 实际归还电源后讨论兑现承诺，并检查许宁未获得陈默私有历史；优先复用第4个场景的同局记忆 |
| 6 / `reviewed_rescue_briefing` | 基于已知事实创作救援简报；检查实际 Author/Reviewer 节点以及完成交付后的正式发布记录 |

`--only` 接受编号或表中的 ID，便于逐个控制费用；不指定则依次执行未尝试场景。`--probe-only` 仍兼容，等价于只做第1个场景。当前已保存的成功 CompatibilityProbe 共208 token，会登记为第1个场景并保留原账本，不额外再跑一次。

功能场景使用 `test_engine_routes` / `test_engine_power` 的合法动作辅助函数准备检查点，明确标注 **deterministic checkpoint preparation**。准备过程可以包含作者排练中的合作约定，但不会直接注入成功 flags，也不会把这些准备动作归为 AI 效果；切换 live 后才进行本场真实调用。第5个场景若单独运行且没有第4个的存档，会准备新的确定性场景，并如实标记未覆盖先前 live 记忆。

模型确实提出可执行计划时，脚本提交该计划并至多完成一个合法批次，记录实际动作、物品变化及待满足条件。模型没有给出方案、规则阻塞、Author/Reviewer 未触发或内容未发布，都保留 `not_covered` 等结果，不能当作通过。整个流程不宣称完成任何完整路线的 live 验证，也不额外调用 Judge。

六个场景的所有模型节点、审核、修复和第1个探测合计受同一200,000 token账本限制。每个场景开始前就写 attempt 标记，重复运行不会自动重跑已尝试场景；不支持静默升级模型。

默认报告为 `artifacts/live-qwen-report.json`；累积账本与进度在 `artifacts/live-qwen-budget/`。只有完整接收并记录了台词的测试适配器才 ACK。报告区分成功完成交谈、工程守卫与未评分的人物质量；Windows Unity Editor/Player 表现必须另行实测。
