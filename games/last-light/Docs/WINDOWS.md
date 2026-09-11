# Windows 启动、构建与验收

本机 Mac 完成的是源码、规则、接口和 CPU Mock 验证。Windows Player 的编译、画面、帧率和实际操作由下面流程取得，不以 Mock 报告代替。

## 打开工程

1. 使用 Unity Hub 安装 **Unity 6000.0.62f1**，包含 Windows Standalone 支持。将本目录作为已有项目加入 Hub。\
   **作用：** 使用锁定的引擎版本，避免包与 API 漂移。
2. 在工程目录打开 PowerShell，运行 `powershell -ExecutionPolicy Bypass -File tools/setup_windows.ps1`。\
   **作用：** 创建项目专用 Python 环境并安装随包 NPC Director 和后端依赖；不修改其他工程。
3. 在 Unity 打开 `Assets/Scenes/LastLight.unity`，等待首次导入完成；必要时执行菜单 `Last Light > Configure project`，随后重启 Editor。\
   **作用：** 创建 URP 与中文字体资源、导入独立 FBX 为人物/道具 Prefab 与动作片段，并启用新 Input System。场景通过 Bootstrap 创建完整游戏。
4. 点击 Play。\
   **作用：** 客户端自动尝试启动本地后端。若已手工启动，可在游戏设置中指定同一端口。

## 模型与离线演练

1. 将 `.env.example` 复制为 `.env`，按模型服务填写地址与密钥；不要把 `.env` 提交或发到聊天里。\
   **作用：** 凭据只被后端读取，Unity 不持有模型密钥。
2. 若使用已配置的本机 Codex provider，可设置 `LAST_LIGHT_USE_CODEX_AUTH=1`。不能同时配置另一个不匹配的服务地址。\
   **作用：** 在凭据原本所属的服务上复用现有配置，运行时读取而不复制密钥。
3. 默认模型为 `qwen3.8-flash`，`LAST_LIGHT_API` 可为 `chat_completions` 或 `responses`，以服务端支持方式为准。\
   **作用：** 正确选择传输接口，避免把 API 不兼容当成人物问题。
4. 暂无模型时选择“预设演练”。\
   **作用：** 使用明确标识的作者回应验证救援规则；它不等同于真实 AI 体验。

后端默认监听 `127.0.0.1:8765`。若端口被其他服务占用，可运行 `.venv/Scripts/python.exe tools/run_server.py --port 8766`，并在游戏设置中改为 `http://127.0.0.1:8766`。

## 一键构建

运行 `powershell -ExecutionPolicy Bypass -File tools/build_windows.ps1`。非默认安装路径添加 `-UnityPath "D:/Unity/.../Editor/Unity.exe"`。\
**作用：** 自动运行无模型测试、打包 Python 后端、验证 Unity 资源并构建 Windows Player；任一环节失败都会停止，不生成假通过记录。

结果位于 `Builds/Windows/`。发行时复制整个目录，不能只复制 `LastLight.exe`；首次使用模型时在该目录创建 `.env`。\
**作用：** 保留 Unity 数据目录与 `runtime/last-light-server.exe`，让独立包无需源代码工程即可启动服务。

## 画面与操作验证

运行 `powershell -ExecutionPolicy Bypass -File tools/verify_windows.ps1`。\
**作用：** 使用真实 Player 渲染从权威规则生成的场景与行动夹具，输出三种分辨率截图、独立采集的动作帧、按时间戳编码的短视频和硬件记录；不会调用模型。

随后手动完成一次留车路线和一次撤离路线，观察：

- 05在未观察前无内部透视；人物点击、WASD/E、输入框互不穿透。
- 清走推车后，门仍需单独释放；门、碰撞和可达性一致。
- 电源仅有一个实例；递接、接线、断开、归还可见，电量不恢复。
- 维修后仍需复测；母亲和小满实际随队伍转移。
- 对话全文显示后点击继续才确认送达；取消和重连不会重复提交。
- 1280×720、16:10、长对白、笔记与计划均可操作；低画质保留状态提示。
- 结局没有自动补齐缺席者；存档恢复同时恢复人物记忆和任务。

保存 Player 日志、截图与 `qa-report.json`。性能报告中的 GPU/CPU 与帧率必须来自这台 Windows 机器，不以开发目标代替。

人物源文件、独立导出资产和 Director 演出字段见 [表现说明](PRESENTATION.md)。`setup_windows.ps1` 会安装视频编码依赖，不要求另行手动配置 FFmpeg。
