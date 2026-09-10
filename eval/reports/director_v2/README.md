# NPC Director V2 评测证据归档

本目录归档本轮 `artifacts/director-v2/` 的关键证据，随代码提交，保证克隆仓库后链接仍可使用。
`.json` 是便于审阅的摘要，保留评分、检查、对话与用量；同名 `.json.gz` 保存完整原始报告，
包括 trace、全部调用和最终上下文，解压后字节与原文件一致。原始 artifacts 未移动或覆盖。
文件摘要、原路径、压缩与原始 SHA-256、报告完成状态见 [manifest.json](manifest.json)。
运行脚本默认继续把新报告写到 artifacts。

例如读取完整报告：

```bash
gzip -dc eval/reports/director_v2/episodes-live-sol-release-34x3.json.gz > /tmp/npc-director-report.json
```

| 可读报告摘要（完整报告为同名 `.gz`） | 用途与结果 |
|---|---|
| [episodes-live-sol-release-34x3.json](episodes-live-sol-release-34x3.json) | 完整 102 次真实运行；97 次成功；自然度 4.59、人设 4.91 |
| [episodes-live-sol-final-content-regressions.json](episodes-live-sol-final-content-regressions.json) | 最后修正后九类内容场景各三次；结构 27/27，质量 26/27 |
| [episodes-recorded-final.json](episodes-recorded-final.json) | 最终代码的 102 次脚本运行，结构全部通过；没有模型质量分数 |
| [live-sol-objective-version-regression.json](live-sol-objective-version-regression.json) | 版本修正复测；版本错误 0/3，整体 2/3，含一次预算降级 |
| [demo-final.json](demo-final.json) | 无需 Unity 的完整协作与内容邀请示例，脚本模式 |
| [pytest-final.log](pytest-final.log) | 最终 460 项 Python 测试通过记录 |
| [episodes-live-sol-34x3.json](episodes-live-sol-34x3.json) | 中间版本完整运行，82/102，不作最终验收 |
| [episodes-live-sol-34x3-final.json](episodes-live-sol-34x3-final.json) | 名称虽有 final，但运行主动中断；仅作诊断，不能作完整报告 |
| [live-luna-pilot-32.json](live-luna-pilot-32.json) | 早期 Luna 真实试跑，8/32 |
| [live-luna-compiled-candidates.json](live-luna-compiled-candidates.json) | 内容返修与复杂协作问题的四场景诊断 |
| [live-sol-shared-conversation.json](live-sol-shared-conversation.json) | 交谈送达定向复测，2/2 |
| [live-sol-branch-event-check.json](live-sol-branch-event-check.json) | 父任务分支与世界事件定向复测，2/2 |
| [demo-reviewed-cooperation-final.json](demo-reviewed-cooperation-final.json) | 较早脚本示例，保留引用；实际使用优先看 demo-final |
| [cases-before-final-calibration.jsonl](cases-before-final-calibration.jsonl) | 最后一轮用例校准前快照 |

完整 102 次与最后 27 次对应不同代码时点；模型、代码和数据集还曾同时改变，不能把不同报告
当作严格单变量对照，也不能用定向复测替换完整套件中的失败样本。

说明：[验收记录](../../../VALIDATION_DIRECTOR_V2.md)、[评分标准](../../../EVALUATION_STANDARDS.md)、
[实施复盘](../../../ISSUE_LOG.md)。旧 `eval/reports` 下的历史报告保持原样。
