# 持续行为模式与记忆生命周期

认知链是通用后端的可选功能。它复用 v2 的角色隔离、Planner、治理、发言仲裁及完成事务，
不改变 `PerformanceDirective 1.0`，也不要求修改 Unity 或游戏适配器。
完整结构图见 [架构说明](AGENT_ARCHITECTURE.md)，实际结果见 [验证记录](VALIDATION_COGNITION.md)。

## 启用与宿主生命周期

```bash
export NPC_DIRECTOR_COGNITION=true
export NPC_DIRECTOR_MODEL=gpt-5.6-luna
export NPC_DIRECTOR_MODEL_PROFILE=idealab_qwen
# 可选；留空则反思沿用 NPC_DIRECTOR_MODEL。
export NPC_DIRECTOR_MEMORY_MODEL=gpt-5.6-luna
```

作用：为新 episode 固定 `memory-v1` 策略。现有 episode 保持原版本，未标版本的历史 episode
按旧路径恢复。默认 `false` 保留 v2 兼容模式；本功能是否达到质量门槛需阅读验证报告。

HTTP 服务通过 FastAPI lifespan 启停维护 worker。直接使用 Python 的宿主采用：

```python
service = build_default_service(settings)
await service.start_memory_maintenance()
try:
    # 原有 run_turn / start_episode / publish_event / process_engine_event
    # 继续负责对话、世界事件和完成回执。
    ...
finally:
    await service.stop_memory_maintenance()
```

作用：维护与前台推理解耦。退出取消在途维护，未知用量按已预留额度结算，事实不会回滚。
测试和需要确定性时序的宿主可使用：

```python
await service.drain_memory_jobs(session_id, limit=16)
snapshot = service.get_cognition(session_id, npc_id)
```

作用：显式处理有限数量的维护任务，并读取当前模式、记忆来源、关联和维护状态。
`get_cognition` 是受信 Python 调试接口，包含角色私有数据，不暴露为公开 HTTP 接口。
不要在演出完成回调里同步等待真实反思；实际 API 服务由独立 worker 处理。

## 模式配置

不填写 `behavior_modes` 时使用 neutral、guarded、cooperative、investigative、task_focused。
非空 `behavior_modes` 是该角色的完整目录，`initial_behavior_mode` 必须出现在其中。例如：

```json
{
  "initial_behavior_mode": "neutral",
  "behavior_modes": [
    {
      "mode_id": "neutral",
      "purpose": "正常交流，保持既有人设",
      "entry_conditions": ["无持续冲突"],
      "exit_conditions": ["出现明确威胁或证据矛盾"],
      "allowed_operations": ["lore", "consult_npc"]
    },
    {
      "mode_id": "guarded",
      "purpose": "保护边界，允许核实后有限合作",
      "entry_conditions": ["收到明确威胁"],
      "exit_conditions": ["新证据解除顾虑"],
      "allowed_operations": ["lore", "consult_npc"]
    }
  ],
  "protected_memory_refs": []
}
```

作用：这是附加到原有角色 JSON 的配置片段。操作范围与现有能力权限取交集；缺省的操作范围
为全部六种编排操作，但仍不增加任何游戏动作或状态权限。进入/退出的语义由 Planner 与
Quality Judge 判断，来源有效性、目录和操作范围由代码检查，不执行配置中的任意代码。

`protected_memory_refs` 可列记忆 ID、事件 ID 或事件所带的内容引用，使相关经历不参与普通衰减。
模式与情绪分开：保持戒备不要求每句都愤怒。Planner 在现有调用内提出模式，不新增逐拍模型调用。

模型优先使用 `e1`、`m1` 等当前角色的短引用；后端恢复其正式 ID，并保留来源。
可见的回合 ID 也映射到对应已记录事件。未注册模式、越界引用和无依据的完成退出不会生效；
trace 记录拒绝理由，后续计划按旧模式继续校验。无效的记忆使用标注只停止对应强化，不替换有效回答。
模式状态与完成事务一起持久化，中断或失败的候选不写入。

## 记忆类型、召回与生命周期

- `experience`：实际收到的对话或世界事件。玩家陈述和 NPC 报告保持 `reported`，不因写入记忆而变真相。
- `commitment`：完成交谈中形成的承诺；开放状态受保护，履行仍需要既有任务/证据规则确认。
- `summary` / `belief`：模型生成的经历摘要和人物判断，标记 `inferred`，默认仅当前 NPC 可见。
- `legacy_unverified`：来自旧 scoped 记忆、未重新核验来源的记录，保留原 ID 与来源回合。

编码由实际事件和结构化承诺状态驱动。跨 NPC 记忆只来自真实完成送达后的受众，不广播私有历史。
共同人物、目标、事件及支持/反驳/取代关系建立关联。取代只允许作用于旧摘要/判断，并必须引用较新的证据。
原始经历和承诺不会被反思改写，旧判断仍保留并标记 `superseded` / `disputed`。

BM25 在本实例、本 NPC 的全量记忆池上建立版本缓存，不再先截断最高重要度的 256 条。
检索合并明确关联的候选，保留来源并去重；最多六条，序列化记忆合计最多 1600 token。
近期十二条原文、当前任务和未完成承诺继续由权威状态提供。尚未引入 embedding 或跨账号共享。

事件计数推进遗忘，每三十二条新增可见事件默认衰减一半，激活度低于 0.1 时休眠；
查询、重复回执、后台轮询和现实时间流逝不推进该时钟。休眠数据可被明确查询找回。
只有合法完成回合中引用的有效记忆被强化；开放承诺、活动目标与配置保护分别保留原因。
到期来源不用于当前召回或新反思，已有权威事件仍然保留。

## 反思、预算与故障

承诺变化、明显关系变化、威胁/重大选择、证据冲突或累计八条未整理事件触发反思。
每个角色同时只保留一个 pending/running 任务，冻结最多三十二条相关记录；任务不触发新的游戏行动。
反思输入使用短引用，提交时恢复正式来源并检查版本。旧快照结果标记 `obsolete`，根据最新已收到
事件合并新任务；不重新开启被取消的游戏 episode。

在事务中入队前预留来源 episode 的一次模型调用和保守 token，反思输出上限 1536 token。
预算不足时继续保留已编码事实，等待之后的合适事件。维护使用与前台相同的模型并发限制。
任务有租约、幂等键和至多两次尝试；每次重试重新预留，不复用旧调用的收费凭证。
模型、格式或来源检查失败不撤销游戏事实。进程丢失响应时按预留记账，晚到结果不能覆盖已经结算的用量。

配置项：`NPC_DIRECTOR_MEMORY_HALF_LIFE`（32）、`NPC_DIRECTOR_MEMORY_REFLECT_AFTER`（8）、
`NPC_DIRECTOR_MEMORY_DORMANT_THRESHOLD`（0.1）。括号内为默认值。

## 迁移、回退与验证

SQLite schema 3 以新增表保存认知状态、来源、关联、任务和效果去重键；不删除旧表。
迁移只读取 scoped 记忆，保留 ID 与原始来源回合，不把旧全局数据复制到新世界。
关闭开关使新 episode 回到旧编排/记忆路径；已固定为 memory-v1 的 episode 及已预留维护任务
继续按原策略处理。需要停止维护时使用显式 stop 方法，数据仍保留。

```bash
.venv/bin/python -m pytest
.venv/bin/python -m scripts.run_episode_eval --cognition --mode recorded --repeats 3
.venv/bin/python -m scripts.run_episode_eval --cognition --mode recorded \
  --cases eval/cases/cognition.jsonl --repeats 3
```

作用：分别检查工程回归、旧 34 个场景和新增十二个模式/记忆场景。
`--case cog_reflection` 可查看编码—反思—后续回应的通用例子；`--case cog_revision` 查看新说法
出现后保留来源的处理。recorded 明确使用 fixture，不代表真实模型的自主学习或自然度。

live 必须保持同一持久账本：`NPC_DIRECTOR_EVAL_LEDGER=artifacts/cognition/live-budget.db`，
试点 phase 为 `pilot`（累计最多 30 万），正式和后续重测为 `full`，所有 phase 合计最多 1000 万。
生成、反思、独立 Judge、重试及未知用量都计入；停止或重启不退还未知调用，不删除账本重置额度。
所有报告分别保留来源、源码摘要、用量和失败；中断报告不是完整验收。
