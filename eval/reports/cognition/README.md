# 持续模式与记忆生命周期验证证据

工程与完整结论见 [VALIDATION_COGNITION](../../../VALIDATION_COGNITION.md)。

- `recorded-combined-final.json`：最终代码，旧34×3＋新12×3，138/138。
- `live-memory-release-36.json`：完整新增Luna批次，27/36，未达到90%门槛。
- `live-v2-release-102.json`：预算停止，只处理78/102，不能作为完整回归质量结论。
- `live-pilot-*`、`live-alias-*`、`live-mode-normalization-check`：诊断与定向复测。
- `live-memory-36`、`live-v2-regression-102`：早期被主动中断的批次，保留中断标记与失败。
- `token-ledger.json`：所有试点、诊断、正式、反思、Judge及未知调用共用的账本摘要。
- `manifest.json`：完整压缩报告与原始字节的SHA-256。

`.json` 是可读摘要；同名 `.json.gz` 是未经改写的完整原件。原 artifacts 保持原样。
最后的空分析修复与Judge输入修复已经离线验证，但没有预算后的新live成绩；不要把其结果
倒填到上述75%或预算截断报告中。
