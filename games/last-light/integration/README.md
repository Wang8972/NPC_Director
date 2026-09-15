# Git 与 P4：余灯的存放和同步

本项目沿用 NPC Director 已建立的 Git/P4 分工。`games/last-light` 是代码工作区，**不是可以直接在 Unity 打开的完整游戏工程**。它没有美术二进制、场景、ProjectSettings、构建包和模型凭据。

| 内容 | 唯一编辑来源 |
|---|---|
| Python 后端、测试、Unity C#/Editor、动作与挂点配置、生成工具、文档 | 此 Git 仓库 |
| Blender/FBX、美术、音频、字体、Unity 场景与工程设置 | 独立 P4 工作区 |
| P4 中的代码和源代码 `.meta` | 从 Git 同步的只读快照，修改应回 Git |
| Library/Temp、SDK 下载缓存、运行数据库、密钥、构建包、截图录屏 | 不入 Git/P4 的运行目录或独立交付制品 |

经用户明确要求，`deliveries/2026-09-15` 保存一份历史游戏存档归档及校验清单；这是对运行数据库默认不入库规则的一次显式例外。不包含应用包或模型凭据，恢复方法见 [源码构建与游玩教程](../README.md#6-使用仓库中的游戏存档)。日常运行目录仍不提交。

`assets.lock.json` 列出首次资产包的每个文件和 SHA-256，供校验和配套导入；不是美术的第二套 Git 历史。`ownership.json` 记录具体边界。P4 stream 尚未指定，`p4_status=not_uploaded` 表示准备好本地导入包，不表示已在服务器提交。

## 直接运行 Git 中的后端 Mock

1. 在 NPC Director 仓库根目录运行 `python -m pip install -e ".[dev]"`，再运行 `python -m pip install -e "games/last-light[test]"`。\
   **作用：** 安装当前仓库 SDK 与游戏后端，不依赖外部相邻目录。
2. 运行 `python games/last-light/tools/run_server.py --port 8766`。\
   **作用：** 启动权威游戏 API，不加载 Unity 美术。
3. 另开终端运行 `python games/last-light/tools/mock_play.py --smoke` 或 `python games/last-light/tools/mock_play.py`。\
   **作用：** 无模型费用地验证协议和规则，或交互式演练。
4. 在 `games/last-light` 目录运行 `python -m pytest -q`。\
   **作用：** 使用游戏自己的 pytest 配置运行离线回归；仓库根目录的 SDK 测试仍独立保留。

## 首次组装独立工作区

1. 在 Windows P4V 中选定或创建属于《余灯》的工作区，放在 Git 检出目录之外，例如 `D:/P4Workspaces/LastLight`。\
   **作用：** 保持版本控制边界，避免同一目录由 Git 和 P4 同时管理。现有 GreyHarbor 流不被自动复用或修改。
2. 准备本地交付文件 `LastLight-p4-assets.zip`；在仓库根目录运行 `python -m pip install hatchling`。\
   **作用：** 取得与锁清单对应的完整资源，并准备从当前 SDK 源码打包 wheel。已经从 P4 同步资源时，后续同步不需要资产 zip。
3. 运行：

   ```powershell
   python games/last-light/tools/materialize_workspace.py --workspace D:/P4Workspaces/LastLight --assets-archive C:/Downloads/LastLight-p4-assets.zip --check-only
   ```

   **作用：** 只校验文件清单、散列、Git/P4 边界及覆盖冲突，不写工作区，不连接 P4。
4. 去掉 `--check-only` 再运行相同命令。\
   **作用：** 导入资源，复制 Git 代码并从当前 SDK 打包依赖，记录 `.code-sync.json` 的 Git 版本和文件散列；已有不同资产会被拒绝覆盖。
5. 在工作区运行 `powershell -ExecutionPolicy Bypass -File tools/setup_windows.ps1`，使用 Unity 6000.0.62f1 打开该工作区并执行 `Last Light > Import art`。\
   **作用：** 安装后端、从随包 FBX 生成 Prefab、材质和动作目录，形成完整 Unity 工程。无需在 Windows 安装 Blender才能游玩。
6. 使用 P4V 检查新增/修改文件和 `.meta`，确认忽略 Library、缓存及凭据后提交一次资产导入 changelist。\
   **作用：** 完成真正的 P4 上传；本仓库同步脚本不会替用户创建服务器、stream 或提交 changelist。

## 后续代码更新

1. 在 Git 仓库修改、测试并提交代码。\
   **作用：** 保留唯一可评审的代码来源。
2. 对 P4 中需要更新的派生代码快照进行 checkout，再运行 `materialize_workspace.py --workspace ...`，不带资产包。\
   **作用：** 同步代码与 SDK wheel，保留美术；如发现工作区中有人直接改过代码，停止并提示先处理冲突。
3. 根据 `.code-sync.json` 检查 Git revision，并在 P4V 提交更新后的派生快照。\
   **作用：** 保持代码和资产的版本对应。`source_dirty=true` 表示来源含未提交修改，不应当作正式构建基线。

普通克隆不自动下载美术。当前 Mac 未配置 P4，首次 P4 changelist 和 Windows Player 验证仍待执行；已完成的本地测试摘要见 `validation-summary.json`。
