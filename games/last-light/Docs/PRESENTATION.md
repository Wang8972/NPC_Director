# 人物、物品与演出实现

本次补齐独立低模资产、完整 Director 演出字段、表现时钟、物品唯一实例和动作结果演出。仍未在 Unity Editor 或 Windows Player 执行验证；本机预览来自 Blender，不是游戏录屏。

## 资产实际位置

| 内容 | 文件位置 |
|---|---|
| 九个人物的可编辑网格、蒙皮和面部形变 | `Art/Source/{player,lin,zhou,chen,xu,mother,xiaoman,passenger05,passenger07}.blend` |
| 人物 FBX | `Assets/LastLight/Art/Characters/` |
| 道具与车厢模块源文件、FBX | `Art/Source/` 与 `Assets/LastLight/Art/Props/` |
| 52 个骨骼动作源文件与导出文件 | `Art/Source/motion.blend`、`Assets/LastLight/Art/Motion/rescue_motion.fbx` |
| 导出清单、校验散列 | `Assets/LastLight/Art/manifest.json` |
| 51 项行动与挂点定义 | `Assets/LastLight/Resources/Presentation/Actions.json`、`Sockets.json` |
| 有来源标记的人物、表情、动作预览 | `artifacts/presentation/` |

这些 FBX 是已生成的实际文件。Unity 导入器从 FBX 生成 Generic 模型 Prefab、独立 `.anim` 片段、URP 材质和 PresentationAssets 目录，保存到 `Assets/LastLight/Generated/Art/`。角色不再使用运行时方块拼接；车厢外壳保留原模块布局，座椅和关键设备使用导出模型。

九个角色共享骨架结构，通过服装、头发、配饰与比例区分。九种表情加眨眼形变按强度播放；不做口型或 TTS。道具包括备用电源、辅助设备、工具包、备件、仪表、工具、手电、水杯、担架、推车、门、供电柜、电话、夹板和工作人员钥匙等。

## 演出与权威边界

`DialogueLine.performance` 保留完整情绪、各最多六条脸部/身体 cue、凝视、voice_style 和 interrupt_policy。机密证据、trace、模型运行元数据不会透传。旧对白通过显式兼容映射播放。

新接口 `POST /sessions/{sid}/talk/{job_id}/performance-events` 接收 `line_id`、`event_id`、`event_type`、`visuals_skipped`。收到包和开始播放只更新播放状态；全文展示并继续后才能 completed，从而提交已送达的社会反馈。旧 `/ack` 是标为 legacy 的完成入口。重连、重复事件和取消不提前完成对白。

字幕与人物采用同一表现时钟。菜单和失焦暂停该时钟；显示全文不等于完成，略过动作也不执行救援。Director 的 `reach_out` 不交出物品，`step_forward` 不改变权威位置。身体动作长度来自资产，头眼及面部覆盖层不会被新世界快照清空。

每个行动明确映射准备、结果和失败片段。Unity 先接近并准备，再调用 `/complete`，最后依照实际结果播放尾段。部分完成与失败不播放整项成功；已提交事实不能被取消尾段撤回。物品使用稳定 ID，在持有人、设备和场景之间绑定同一个模型；仪表等子件属于工具包，不能独立生成新库存。

同场头像取当前说话人并复制实际表演采样；远处保留最后观察到的静态头像，未见过的人不生成实时头像。母亲和孩子的关注、照护与姿态只使用投影允许的信息。

## 本机复现与检查

1. 在 Unity 执行 `Last Light > Import art`，或运行 Windows 构建脚本。\
   **作用：** 从随包 FBX 创建 Prefab、材质及动画，并校验骨架、表情、51 项行动和挂点；缺失资源时明确停止。
2. 需要编辑造型时，用 Blender 4.5 打开 `Art/Source` 中的源文件；需要重建全部原始资产时运行 `blender --background --threads 4 --python-exit-code 2 --python tools/build_art.py`。\
   **作用：** 生成可复现的模型、骨骼、形变、动作及源文件，保留制作依据；普通 Windows 游玩不需要安装 Blender。
3. 运行 `blender --background --python-exit-code 2 --python tools/verify_art.py`。\
   **作用：** 实际回读导出的 FBX，检查骨架、权重、非空表情形变和全部动作；不冒充 Unity 导入验证。
4. 运行 `blender --background --threads 4 --python-exit-code 2 --python tools/render_presentation_art.py`，随后运行 `python tools/assemble_art_previews.py`。\
   **作用：** 从源资产渲染人物转台、表情对照与动作预览，再加上明确来源标签；后一步需要 Pillow。
5. 运行 `python tools/generate_presentation_fixtures.py`。\
   **作用：** 从真实规则执行生成 7 个场景视图和 30 组行动序列，包含电源、检修、转移、部分完成、取消及危机中断；没有模型调用。
6. 在 Windows 构建并运行 `tools/verify_windows.ps1`。\
   **作用：** 用实际 Player 验证演出与状态，按独立协程采集中间帧，并按真实时间戳编码短视频。三种分辨率的断言、硬件记录、图片与视频保存在 `artifacts/windows-*`。

## 当前证据边界

本机可证明后端协议与规则测试、独立 C# 时间线测试、C# 语法检查、FBX 回读以及 Blender 预览。额外的演员核心 API 编译使用 Unity 2021.3 参考程序集，只检查这一小部分 API 调用，不能证明锁定的 Unity 6000.0.62f1 全工程已编译。

本次没有新增真实模型调用。此前真实 AI 仍有未通过项，验收账本保留 191,718 / 200,000 token。Windows 画面、交互接触精度、性能和实际游戏时长须由 Player 验收取得。
