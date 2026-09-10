# NPC Director 架构升级验证记录

本次只升级通用后端、契约、状态、提示词、评测和文档。Unity、原型及其适配器源码未改。
默认入口是 `build_default_service()` 的事件驱动 bounded 链，保留旧 `run_turn`、
`PerformanceDirective 1.0` 和 ReAct 消融路径。

自然度、人设的实际评分规则及局限见 [评分标准](EVALUATION_STANDARDS.md)；实施中走过的弯路与
解决方案见 [统一问题与复盘记录](ISSUE_LOG.md)。报告的关键证据已保存到
[版本化归档](eval/reports/director_v2/README.md)：JSON 摘要便于审阅，同名 `.json.gz` 保留完整轨迹，
解压后与原文件逐字节一致，原始 artifacts 保持不变。

## 验收结果

| 验证 | 结果 |
|---|---|
| Ruff / diff 检查 | 通过 |
| Python 全部测试 | **460 passed**，18.00 秒 |
| 最终代码 recorded：34 场景 × 3 | **102/102**，无 fallback |
| 完整 live：34 场景 × 3 | **97/102，95.10%**；结构检查 99/102；1 次 fallback |
| 完整 live 自然度 / 人设 | **4.59 / 4.91**（满分 5）|
| 完整 live 完成度 / 连续性 / 演出一致性 | 4.84 / 4.91 / 4.85 |
| 最终内容与持久化 live：9 场景 × 3 | **26/27，96.30%**；结构与状态检查 **27/27**；无 fallback |
| 最终定向 live 自然度 / 人设 | 4.67 / 4.81 |

完整 live 达到 90% 成功率、自然度和人设平均 4/5 的目标。完成完整报告后，又修正了
目标版本来源、父任务定义持久化和闲聊过早创建委托；最终代码的九类内容场景已另行重复三次。
这 27 次报告的源码摘要与当前代码一致，**没有用定向复测覆盖完整报告中的失败样本**。
任务版本的单独三次复测未再出现版本错误，整体质量 2/3，另一次是预算降级，仍保留原记录。

报告入口：

- [完整 live 报告](eval/reports/director_v2/episodes-live-sol-release-34x3.json)
- [最终 27 次内容与持久化 live 报告](eval/reports/director_v2/episodes-live-sol-final-content-regressions.json)
- [最终 102 次 recorded 报告](eval/reports/director_v2/episodes-recorded-final.json)
- [目标版本定向复测](eval/reports/director_v2/live-sol-objective-version-regression.json)
- [完整测试输出](eval/reports/director_v2/pytest-final.log)
- [无需 Unity 的最终协作示例](eval/reports/director_v2/demo-final.json)

## 边界检查与剩余失败

最终 27 次内容回归中，未审核内容发布、重复副作用、私有知识越界、应归父任务却新建支线、
中断后发布内容及父任务定义未持久化的检查失败次数均为 **0**。460 项回归还覆盖越权提交、
私密审核意见泄漏、到期发布回滚及并发额度；所有相关断言通过。

完整报告的五次失败分别是：一次目标版本错误、一次未知事实未提出查证方法、一次预算降级、
一次三方协作误解巡逻记录、一次闲聊过早创建委托。目标版本和闲聊问题已修正并另行验证。
最终内容回归还留有一次合并任务的语义偏差：台词把“征询接收意愿”说成“交付并确认收到”；
没有产生重复任务或重复奖励。质量指标达到门槛，不意味着所有自由输入都会成功。

## 实测用量与延迟

模型为 `gpt-5.6-sol`，SDK transport，`idealab_qwen` 中性 profile，节点 low reasoning，
并发 3，每次调用超时 60 秒；episode 的 96,000 token / 180 秒预算保持原默认值。

| 指标 | 完整 102 次 | 最终定向 27 次 |
|---|---:|---:|
| 已回报生成 token | 4,694,262 | 1,133,674 |
| 独立 Judge token | 237,975 | 67,638 |
| 生成模型调用 | 1,205 | 280 |
| 未返回用量的失败调用 | 2 | 1 |
| 每场景生成延迟中位数 | 45.13 秒 | 46.00 秒 |
| 每场景生成延迟 P95 | 120.88 秒 | 65.71 秒 |
| 每场景生成 token 中位数 | 36,674 | 39,384 |

延迟包含该场景全部玩家回合、NPC 自主回合和状态处理，不含最终独立 Judge，也不是单拍延迟。
未返回 usage 的失败调用按预留额度扣预算，上表 token 仅统计供应商实际回报部分；未配置价格，不推算费用。

## 实现与回归范围

- 复合目标与有依赖的执行计划；咨询后的操作等待真实回复，格式错误只修复对应节点。
- 多 NPC 独立上下文、交谈内消息送达、汇总合并、玩家抢占、持久任务与预算。
- 行动、父任务步骤、分支、独立支线分层；创作、独立审核、一次定向返修、暂存及原子发布。
- 暂存 ID 与权限在最终台词前冻结；发布、接取和完成分开，重复回执不重复提交。
- 世界事实、角色认知和说法分开；私有审核意见通过固定编辑代码返修，摘要不能证明事实或承诺完成。
- 临时事实到期、发布失败回滚、取消后 outbox 清理、额度释放、跨实例与私有知识隔离。
- 最近 12 条服务端原文与相关长期记忆；客户端历史始终是未核验补充。
- 父任务步骤/分支定义在完成事务中独立保存，超过对话窗口及进程重启后仍可读取，且不冒充执行进度。

原有事实、权限、协议、回放与原型测试继续运行。原型测试只更新模型输出 fixture，
使它能重放新的通用 Planner 和 Quality Judge 契约。意图不再强制映射情绪；
旧的路由断言已按短路径、返回式谈判与延后协商更新。

新增故障回归覆盖模型原生 schema 解码失败、预算 token 预留、配置凭据进程内复用、
无效执行图、修订私有信息泄漏、发布到期、重复消息和内容发布权限冻结时序。

## 数据集与评判边界

当前为 34 个连续对话场景，每个重复 3 次。recorded 只替换模型返回，继续使用生产服务、
审核准入、数据库与完成事件，不能证明人设或自然度。live 逐次使用独立的整段对话 Judge；
所有失败、降级和 Judge 失败都保留在分母。成功率目标为 90%，自然度与人设均值目标为 4/5。

评测设置经过以下校准，未降低四层内容准入标准：

- 独立短支线明确请求一项可拒绝的委托；普通询问另设 `casual_suggestion` 场景。
- 新增可持续事件与复用已有问路步骤分别设置场景，后者明确步骤已存在。
- 复合协作向真正持有信息的角色提供值守记录及护送条件，其他 NPC 只能在送达后得知。
- 无动机复仇允许 Director 直接拒绝，无须为拒绝而强制调用 Author；Author/Reviewer 的拒绝路径另有回归测试。
- 重复内容回执场景给出旧信的具体人物动机、独立目标和结束条件，避免以“它是一条支线”代替必要素材。
- 初始 setup 描述对话前状态；后续明确接受或撤回仍有效。新玩家输入与重复引擎回执分别评价。

校准前的用例保存在 [原始用例快照](eval/reports/director_v2/cases-before-final-calibration.jsonl)。
因模型、代码与场景设置均有变化，各轮数字不能作为严格的单变量对照。

## 已保留的诊断报告

- [首轮完整 Sol 评测](eval/reports/director_v2/episodes-live-sol-34x3.json)：82/102；
  自然度 4.50、人设 4.76，未达到成功率门槛。
- [交谈送达定向复测](eval/reports/director_v2/live-sol-shared-conversation.json)：2/2。
- [父任务分支与世界事件定向复测](eval/reports/director_v2/live-sol-branch-event-check.json)：2/2。
- `episodes-live-sol-34x3-final.json` 在发现中间角色重复唤起后主动中断，不能作为完整验收报告。
- [无引擎协作示例](eval/reports/director_v2/demo-reviewed-cooperation-final.json)：脚本演示通过，内容只进入邀请状态。

其他 Luna 诊断报告与原有 `eval/reports/live_main_sub_*` 报告均保留，未覆盖。
完整报告与最终修正后的定向回归分别列于上文，后者不替代原始 102 次统计。

## 复现

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -o addopts='' -q
git diff --check
.venv/bin/python -m scripts.run_episode_eval --mode recorded --repeats 3
NPC_DIRECTOR_MODEL_PROFILE=idealab_qwen .venv/bin/python -m scripts.run_episode_eval \
  --mode live --transport sdk --model gpt-5.6-sol \
  --repeats 3 --concurrency 3 --call-timeout 60
.venv/bin/python -m scripts.run_episode_demo --mode recorded
```

live 复用用户已授权的本机 Codex provider 配置，仅在评测进程内加载凭据；报告不包含凭据。
保留实际生成 token、调用延迟、fallback、未知用量及独立 Judge 调用，费用只有配置单价后才估算。
单条报告还记录数据集和源码摘要；生成延迟包含同一场景中的所有玩家与自主回合，不等同于单拍延迟。
