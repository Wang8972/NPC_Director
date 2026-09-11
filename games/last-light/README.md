# 余灯 / LAST LIGHT

> **仓库集成说明：** 此目录仅由 Git 管理代码、测试、配置和生成工具。美术、场景及完整 Unity 工程在独立 P4 工作区管理；不要直接把此不含资源的目录作为完整 Unity 工程打开。
> Git 中运行 Mock、组装 P4 工作区和导入资源的方法见 [Git/P4 操作说明](integration/README.md)。本机证据与大型预览保留在交付包中；此仓库提供 [验证摘要](integration/validation-summary.json)。

Unity 6 的 2.5D 列车救援游戏工程：在05—06—07车厢、检修间与避险通道中探索，与林岚、周屿、陈默、许宁协商，再让真实行动改变人员、物品与设备状态。

## 本次交付状态

**源码、独立低模资产、本地规则与HTTP Mock已落地；这不是已经在Windows验收通过的发行版。**

- 完整开场与引导、探索控制、对话与计划界面、存档、设置、两条救援路线、四类结局均已实现。
- 四人知识、承诺与行动分开保存；设备隔离/维修/复测、借用/交付/归还、联系/检查/团聚均有独立规则。
- 真实NPC Director v2已接入。Qwen的借电重谈场景完成了“回应→方案→实际行动”闭环；复杂多NPC和内容发布的真实验收**尚未全部通过**，失败与预算记录见报告。没有用预设对白伪装真实AI。
- 本机没有Unity Editor。C#语法、独立表现逻辑与Blender资产检查不等于Unity编译、GPU渲染或Windows实测。
- 45–60分钟和GTX1650级1080p60帧是设计目标，尚未人工计时或实机确认。

本轮已新增独立 Blender / FBX 人物、52 个动作、完整表情/凝视协议和物品结果演出；资产位置、再生成与验证方法见 [人物与物品表现说明](Docs/PRESENTATION.md)。

具体结果以 [验收说明](Docs/VALIDATION.md)、[验证记录](artifacts/validation.json)、[真实AI报告](artifacts/live-qwen-report.json)、[问题记录](ISSUES.md) 为准。

## 先在本机 Mock

在已安装本工程与NPC Director依赖的Python环境运行：

```bash
python tools/run_server.py --port 8766
```

**作用：** 启动与Unity相同的权威游戏API；8766用于避开本机已有的8765服务。

另开终端运行：

```bash
python tools/mock_play.py --smoke
python tools/mock_play.py
```

**作用：** 前者自动检查协议、真实动作提交、重复回执和存档；后者可交互游玩预设演练。命令包括 `move cabin06`、`inspect oxygen`、`talk xu`、`actions`、`plan clear_aisle`、`go`、`notes`、`save`、`restore`。

在 Git 布局中使用 NPC Director 仓库根目录的 Python 环境；独立 P4 工作区通过打包的 SDK wheel 安装依赖。详见集成说明。

## Unity / Windows

按 [Windows操作手册](Docs/WINDOWS.md) 执行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/setup_windows.ps1
powershell -ExecutionPolicy Bypass -File tools/build_windows.ps1
powershell -ExecutionPolicy Bypass -File tools/verify_windows.ps1
```

**作用：** 安装依赖、打包本地后端与Windows Player、生成实际Player截图及动作帧。构建失败会停止，不生成假的通过记录。

Unity Hub使用 **6000.0.62f1** 打开项目，主场景为 `Assets/Scenes/LastLight.unity`。首次导入会配置URP、TMP与新Input System。Player应连同整个 `Builds/Windows` 文件夹交付，不能只复制exe。

## 模型配置与预算

复制 `.env.example` 为 `.env`。默认Qwen3.8-Flash、显式JSON校验、无昂贵模型自动升级。密钥只由后端读取；可选择在同一服务地址复用本机已有Codex provider。

- **正式游玩预算**由 `LAST_LIGHT_TOKEN_BUDGET` 控制，默认1,000,000，属于可配置上限，不会自动花完。
- **本次真实验收**独立封顶200,000，所有场景、针对性复测和内容子系统共用持久账本。存档恢复不会退回token。
- 报告区分供应商实际返回用量与失败调用的保守预留记账，不虚构费用金额。
- `rehearsal`为明确标识的预设演练。没有模型也能验证规则，但不等于完整AI体验。

已有六个真实验收场景不会因再次运行脚本而自动重复。不要删除账本或更换目录绕过预算。

## 结构

| 位置 | 内容 |
|---|---|
| `backend/last_light` | 权威规则、角色认知、计划调度、存档、HTTP与真实v2适配 |
| `Assets/LastLight/Scripts` | Unity交互、UI、网络、程序化场景与人物、Windows截图工具 |
| `Assets/LastLight/Resources` | 中文字体、原创合成音频；几何和材质由源码生成 |
| `backend/tests` | 无模型费用的路线、人物、事务、隐私和协议回归 |
| `tools` | 启动、Mock、预算验收、资源生成、打包与Windows构建 |
| `Docs` | 完整规格、规则、AI接入、Windows手册与资产许可 |

运行 `python -m pytest -q` 验证规则。运行 `python tools/render_mock.py --fixtures-only` 生成真实规则投影；独立资产预览的 Blender 命令见表现说明。旧方块几何 PNG 属于历史 Mock，不代表本轮资产。

## 预览

下图为**Blender 独立资产预览，不是 Unity 实机截图**：

![人物资产](artifacts/presentation/characters.png)

[九种表情](artifacts/presentation/expressions.png) · [检修动作预览](artifacts/presentation/repair_kneel.gif)

完整人物基线见 [GAME_SPEC](Docs/GAME_SPEC.md)，当前可执行规则见 [RULES](Docs/RULES.md)。
