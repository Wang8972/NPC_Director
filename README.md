# NPC Director：从源码构建余灯、连接 AI 并开始游玩

《余灯》是基于 NPC Director v2 的列车救援游戏。玩家探索车厢、与 NPC 协商，再确认实际行动。游戏客户端负责画面与操作，本机 Python 后端负责世界规则、存档和模型调用。

本教程以 **Windows 构建和游玩**为主，命令使用 PowerShell。请在允许使用所需编辑器的机器上执行；已卸载 Unity 的本机不需要重新安装，也能运行后端 Mock。当前并没有经过完整 Windows 实机验收的发行包，后端测试通过不等于整局游戏已经验收。

**仅克隆 Git 不能直接构建完整游戏。** Git 保存代码；FBX、字体、声音、场景、`Packages` 和 `ProjectSettings` 在 P4 或单独资源包中。缺少这些文件时，需要先完成第 2 步。本仓库不包含 `LastLight.app`。

原仓库主 README（SDK 架构、接入手册及历史验证说明）已原样保存为 [README 历史版本](README_LEGACY_2026-09-15.md)。本页是仓库的构建与游玩入口。

## 1. 获取源码和 Python 环境

需要 Git、Python 3.11 或更新版本，以及用于构建游戏的 Unity 编辑器。完整资源基线记录的版本为 **6000.0.62f1**，应以资源工作区的 `ProjectSettings/ProjectVersion.txt` 为准；不要直接把 Unity 6 工程当作 2022 工程打开。

```powershell
git clone https://github.com/Wang8972/NPC_Director.git D:\Work\NPC_Director
Set-Location D:\Work\NPC_Director
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" -e "games/last-light[test]" hatchling
```

作用：获取 NPC Director 和游戏源码，安装 SDK、游戏后端与测试依赖。已经有仓库时使用原目录并更新代码，不要重复克隆覆盖。

## 2. 组装完整游戏工作区

Git 目录与 P4 工作区必须分开。下面沿用工作区 `D:\P4Workspaces\LastLight`。

### 已经在 P4 中有完整资源

```powershell
Set-Location D:\P4Workspaces\LastLight
p4 info
p4 sync
Get-Content ProjectSettings\ProjectVersion.txt
Test-Path Assets\Scenes\LastLight.unity
Test-Path Assets\LastLight\Art\Characters\lin.fbx
Test-Path Assets\LastLight\Resources\Fonts\Chinese.otf
```

作用：确认当前 P4 client 正确，获取资源并检查场景、模型、字体存在。`p4 sync` 只同步服务器已有文件；空的 stream 不会自动生成游戏资源。后三项应返回 `True`。

### P4 还没有资源：使用已有资源包

准备与 [资源锁清单](games/last-light/integration/assets.lock.json) 对应的 `LastLight-p4-assets.zip`，例如放在 `D:\Downloads`。该包没有上传到 Git；原开发机器保留于 `last-light/Builds/LastLight-p4-assets.zip`，需要另行取得或先导入 P4。

```powershell
Set-Location D:\Work\NPC_Director
.\.venv\Scripts\python.exe games/last-light/tools/materialize_workspace.py --workspace D:/P4Workspaces/LastLight --assets-archive D:/Downloads/LastLight-p4-assets.zip --check-only
.\.venv\Scripts\python.exe games/last-light/tools/materialize_workspace.py --workspace D:/P4Workspaces/LastLight --assets-archive D:/Downloads/LastLight-p4-assets.zip
```

作用：先检查资源清单、SHA-256 和覆盖冲突，再导入资源、复制源码并从当前 SDK 构建 wheel。脚本不会连接 P4 或替你提交 changelist。

已有完整资源、只更新代码时，改用：

```powershell
Set-Location D:\Work\NPC_Director
.\.venv\Scripts\python.exe games/last-light/tools/materialize_workspace.py --workspace D:/P4Workspaces/LastLight --check-only
.\.venv\Scripts\python.exe games/last-light/tools/materialize_workspace.py --workspace D:/P4Workspaces/LastLight
```

作用：同步 Git 源码和 SDK wheel，保留 P4 美术。受 P4 只读保护的代码快照、模型 `.meta`、生成资源和工程设置需先 checkout；脚本报覆盖冲突时不要强行替换。详细边界见 [Git/P4 说明](games/last-light/integration/README.md)。

## 3. 安装并构建 AI 后端和 Windows 游戏

```powershell
Set-Location D:\P4Workspaces\LastLight
powershell -ExecutionPolicy Bypass -File tools/setup_windows.ps1
```

作用：在完整工作区创建独立 `.venv`，安装 NPC Director wheel、游戏后端和打包依赖，并在不存在时创建 `.env`。

关闭正在打开此工作区的编辑器，然后执行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/build_windows.ps1 -SkipSetup -UnityPath "C:\Program Files\Unity\Hub\Editor\6000.0.62f1\Editor\Unity.exe"
```

作用：运行规则测试，打包 Python 后端，导入资源并构建 Windows Player。请把 `-UnityPath` 改为实际安装路径；编辑器应包含 Windows 构建模块。首次导入可能需要较长时间。

成功后应存在：

```text
Builds/Windows/
  LastLight.exe
  LastLight_Data/
  UnityPlayer.dll
  runtime/last-light-server.exe
  .env.example
  QA/
  Docs/
```

作用：确认游戏和内置后端都已产出。分发时保留整个 `Builds/Windows` 文件夹，不能只复制 EXE。失败日志位于 `artifacts/unity-import.log` 和 `artifacts/unity-build.log`。

## 4. 配置 qwen3.8-max

在 **完整工作区根目录**编辑 `.env`，例如 `D:\P4Workspaces\LastLight\.env`。本教程先显式启动后端，让配置来源清晰可见。

使用自己的模型服务时：

```dotenv
LAST_LIGHT_MODEL=qwen3.8-max
LAST_LIGHT_REASONING=none
LAST_LIGHT_API=chat_completions
LAST_LIGHT_BASE_URL=https://你的模型服务地址/v1
LAST_LIGHT_API_KEY=你的密钥
LAST_LIGHT_USE_CODEX_AUTH=0
LAST_LIGHT_TOKEN_BUDGET=1000000
```

作用：指定模型、接口及累计用量上限。地址与模型必须由服务端实际支持，示例占位符不能原样使用。密钥只由后端读取，不提交 Git/P4，也不要填进 Unity 对话框。

若本机已有可用的 Codex provider，可改为：

```dotenv
LAST_LIGHT_MODEL=qwen3.8-max
LAST_LIGHT_REASONING=none
LAST_LIGHT_API=chat_completions
LAST_LIGHT_BASE_URL=
LAST_LIGHT_API_KEY=
LAST_LIGHT_USE_CODEX_AUTH=1
LAST_LIGHT_TOKEN_BUDGET=1000000
```

作用：让后端读取本机 `.codex/config.toml` 中的 provider 和对应凭据，不复制密钥。Qwen 通过 ideaLAB 时使用 `chat/completions`。若服务需要公司证书，配置受信任的 CA 证书路径；不要关闭 TLS 校验。

## 5. 启动后端，立即进入游戏

PowerShell 窗口 A：

```powershell
Set-Location D:\P4Workspaces\LastLight
.\.venv\Scripts\python.exe tools/run_server.py --port 8766
```

作用：从源码启动与独立游戏共用的权威 API，读取工作区 `.env`；保持此窗口打开。模型调用只有在真实交流等操作发生时才消耗 token。

PowerShell 窗口 B：

```powershell
Invoke-RestMethod http://127.0.0.1:8766/health
Start-Process D:\P4Workspaces\LastLight\Builds\Windows\LastLight.exe
```

作用：先确认本机服务可连接，再启动游戏。健康信息应包含 `app_id: last-light`、`director_ready: true`、`director.model: qwen3.8-max`。**健康检查只确认配置可用，不会实际请求模型。**

在游戏中选择“开始新的旅程”，或进入“存档”选择已有会话。看完或跳过开场后，点击 NPC 走近，输入问题，再点“交谈”。正文显示完后点击“继续”确认送达。行动建议还需在“计划”中确认，NPC 说“我去拿”不等于物品已经交付。

作用：完成从自由交流到实际行动的操作。WASD 用于移动，E 选择附近目标；输入框获得焦点时按键用于打字，点击场景或按 Esc 后恢复移动。

如果暂时没有模型凭据，可以选择“预设演练”。它能验证规则与交互，使用作者预设对白，不是真实 AI。

### 使用打包的后端启动

把 `.env.example` 复制为 `Builds/Windows/.env` 并填写配置，然后在没有其他后端占用 8766 时运行：

```powershell
Set-Location D:\P4Workspaces\LastLight\Builds\Windows
.\runtime\last-light-server.exe --host 127.0.0.1 --port 8766
```

作用：验证第 3 步产出的独立后端，不再依赖 Python 安装。另开窗口运行 `LastLight.exe`。已有服务正在运行时不要再启动第二个；以后也可以让游戏自动启动内置后端。若界面先显示连接失败，等后端启动完成后进入“设置 → 本机服务 → 保存并重新连接”。

## 6. 使用仓库中的游戏存档

存档归档：[LastLight-saves.zip](games/last-light/deliveries/2026-09-15/LastLight-saves.zip)。说明与校验：[存档清单](games/last-light/deliveries/2026-09-15/LastLight-saves.manifest.json)。包含实际游玩、开发测试和失败会话，以及对应 NPC 记忆、检查点与用量账本；不是全部通关的示范存档。归档不含模型凭据。

先关闭游戏及后端，在**新的空目录**解压：

```powershell
Expand-Archive -LiteralPath D:\Work\NPC_Director\games\last-light\deliveries\2026-09-15\LastLight-saves.zip -DestinationPath D:\P4Workspaces\LastLight\data\runtime\import-20260915
Set-Location D:\P4Workspaces\LastLight
.\.venv\Scripts\python.exe tools/run_server.py --port 8766 --data-dir D:\P4Workspaces\LastLight\data\runtime\import-20260915
```

作用：恢复完整的世界和 NPC 记忆，并让后端使用这份副本；不覆盖默认存档。进入游戏“存档”选择会话即可，不能只复制单个世界 JSON 后丢弃 Director 数据库。失败记录会保留，导入不会自动补做未执行的行动。

Windows 默认存档位于 `%LOCALAPPDATA%\LastLight\saves`；macOS 默认位于 `~/Library/Application Support/LastLight/saves`。恢复存档不会退回模型用量，也不应通过删账本绕过预算。

## 7. 没有编辑器时运行后端与 Mock

在 Git 仓库根目录的 Python 环境中：

```powershell
.\.venv\Scripts\python.exe games/last-light/tools/run_server.py --port 8766
# 另开终端：
.\.venv\Scripts\python.exe games/last-light/tools/mock_play.py --smoke
.\.venv\Scripts\python.exe games/last-light/tools/mock_play.py
```

作用：无需 Unity、美术资源或真实模型即可检查 API 和文字版演练。macOS/Linux 使用 `.venv/bin/python` 替换 `.venv\Scripts\python.exe`；环境可用 `python3 -m venv .venv` 创建，再执行第 1 步中的 pip 安装命令。

本机曾产出 Mac 兼容版，但当前 Git 中的 `BuildTools.cs` 没有 `BuildMacOS` 入口，历史 `build_macos.sh` 不能视为已完成的源码构建通路；本教程不以该脚本承诺 Mac 一键构建。当前机器的 Unity 和团结软件已卸载。

## 排查常见问题

| 现象 | 检查与处理 |
|---|---|
| 缺少 FBX、场景或工程设置 | 回到第 2 步。源码仓库不含 P4 资源，只有空 stream 无法构建。 |
| `materialize_workspace` 提示覆盖冲突 | 保存工作区改动并核对 `.code-sync.json`，不要强制覆盖美术或个人修改。 |
| HTTP 连接失败 | 确认窗口 A 仍在运行，检查 `/health`，再在游戏设置里重连。 |
| 端口被占用 | 先确认占用者；必要时在后端 `--port` 和游戏服务地址同时改端口。 |
| `APIConnectionError` | 核对模型地址、凭据来源、网络及证书。健康检查成功不代表真实请求成功。 |
| NPC 回答后没有行动 | 查看“计划”并确认执行；接受任务、开始工作、完成工作是不同状态。 |
| 报错但曾显示或送达对白 | 检查已有任务和物品状态，不要认定整个回合已回滚。保留会话 ID 与错误文本用于诊断。 |
| WASD/E 不响应 | 看是否在开场、菜单、输入框或行动演出中；退出输入焦点或完成/取消当前行动。 |

离线规则测试：在 `games/last-light` 或完整工作区运行 `python -m pytest -q`。Windows Player 图像与演出验证使用 `tools/verify_windows.ps1`，不能用 Python 测试替代实机验收。

更多说明：[玩法与规则](games/last-light/Docs/RULES.md) · [模型与协议](games/last-light/Docs/DIRECTOR.md) · [人物与物品表现](games/last-light/Docs/PRESENTATION.md) · [资源许可](games/last-light/Docs/ASSET_LICENSES.md) · [已知问题](games/last-light/ISSUES.md)。
