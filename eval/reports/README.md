# Eval 报告索引

`*.json` 报告文件不入库（见 `.gitignore`），本索引记录每份报告对应的实验，便于对照复现。

## 离线报告（`make verify` 系列产出，可随时重跑）

| 文件 | 实验 |
|---|---|
| `latest.json` | 36 条 recorded golden eval（`make eval`） |
| `ablations.json` | single / main-sub 固定与动态 / 记忆 / RAG 消融（`make ablations`） |
| `judge_calibration.json` | judge 与人工标签校准（`make judge-calibration`） |
| `load_test.json` | 确定性离线服务压测（`make load-test`） |

## Live 报告（真实模型跑 36 条 golden，命名 `live_<架构>_<模型>_<变体>.json`）

按实验时间顺序：

| 文件 | 实验 | 关键结论 |
|---|---|---|
| `live_single_deepseek_baseline.json` | single_agent + bailian/deepseek-v4-pro，无定制 | 单 Agent 基线 |
| `live_main_sub_deepseek_baseline.json` | main_sub + deepseek，无定制 | 3/36；specialist_routing 11.4%，实证 idealab 网关 tools+structured output 同开时模型不调工具 |
| `live_main_sub_deepseek_prompt_profile.json` | main_sub + deepseek + idealab_deepseek profile（仅 prompt 补丁/限流重试） | 3/36；routing 11.1%，证明 prompt 层修不了路由 |
| `live_main_sub_qwen_baseline.json` | main_sub + qwen3.7-max，无定制 | 3/36；routing 12.9%，另有 5 条 cue 时序 ValidationError 崩溃，证明缺陷是网关级而非模型个例 |
| `live_main_sub_qwen_two_phase.json` | main_sub + qwen + 两阶段 Director + 全部确定性修复 | 10/36；routing 72.4%，cue 崩溃归零 |
| `live_main_sub_deepseek_two_phase.json` | main_sub + deepseek + 两阶段 Director + 全部确定性修复 | 12/36；routing 88.2%，schema 34/36 |

两轮 two_phase 实验与三轮历史基线的详细对比见根 README 6.3 与提交历史。
