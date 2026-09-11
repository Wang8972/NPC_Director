# 本轮人物与物品表现验收记录

本次交付包含 Unity 源码、独立低模源文件及 FBX、Python 后端和明确标识的本地 Mock。Windows Unity 编译、实际画面、交互接触精度、性能和游玩时长仍待用户在 Windows 验证。

| 检查 | 实际结果 | 范围 |
|---|---|---|
| Python 回归 | 113 通过，0 失败 | 规则、人物、协议、播放/送达分离、重连、兼容、真实行动夹具 |
| C# 表现逻辑 | 23 项断言通过 | 实际时间线、表情/动作时序、层级、打断、暂停、枚举与语速 |
| 全工程 C# 9 语法 | 0 错误 | Roslyn 语法检查，不等于 Unity 工程编译 |
| 演员核心 API 参考编译 | 通过 | 使用 UnityEngine 2021.3 参考程序集，仅检查演员/资产/挂点/DTO/时钟，不等于锁定的 Unity 6 全工程 |
| FBX 实际回读 | 通过 | 9 个角色的骨架、全顶点权重、表情形变，以及 52 个骨骼动作 |
| 独立资产 | 已生成 | 9 个角色、22 类道具与模块、52 个动作；导出文件散列一致 |
| 规则执行夹具 | 已生成并检查 | 7 个视图、30 组真实 before/execution/after，含部分完成、取消、危机失败 |
| HTTP Mock | 通过 | 身份、隐私、计划、执行、重复回执、保存与恢复 |
| Unity Editor / Windows Player | 未执行 | 脚本与夹具已准备，不以 Blender 预览代替实机 |

Python 测试有一条 Starlette TestClient/httpx 弃用提示，不影响测试通过。

本轮真实模型调用为 **0**。此前验收继续保留 **191,718 / 200,000 token** 的保守累计记账，其中供应商返回 163,005 token，一次未知用量调用按 28,713 token 预留记账。此前兼容性与许宁重谈的回应—方案—行动闭环通过，复杂多 NPC 与完整内容发布仍有未通过项，本次没有将它们重标为通过。

证据入口：

- [综合记录](../artifacts/validation.json)
- [Python 日志](../artifacts/pytest.log)
- [C# 表现断言](../artifacts/presentation/csharp-timeline-tests.json)
- [FBX 回读记录](../artifacts/presentation/art-roundtrip.json)
- [行动夹具来源](../artifacts/presentation/fixtures/manifest.json)
- [人物预览](../artifacts/presentation/characters.png)、[表情预览](../artifacts/presentation/expressions.png)
- [真实 AI 历史报告](../artifacts/live-qwen-report.json)

按 [Windows 操作手册](WINDOWS.md) 构建和运行 Player。**作用：** 获得三种分辨率的真实截图、动作中间帧、短视频和实际硬件记录；在此之前不将 1080p 60 FPS 或 45–60 分钟目标标记为通过。
