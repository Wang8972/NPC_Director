# 资产来源与许可

- **角色、设备、门、工具、动画与材质**：由本工程 `tools/build_art.py` 原创制作，Blender 4.5.0 输出可编辑 `.blend` 与 FBX，位于 `Art/Source` 与 `Assets/LastLight/Art`。车厢外壳沿用原创模块代码；不依赖商店素材或私人外部路径。
- **环境声音、提示与音乐**：本工程原创合成音频，源脚本 `tools/generate_audio.py`，固定随机种子；`Resources/Audio/manifest.json` 保存文件 SHA-256。没有使用第三方录音。
- **中文字体**：Noto Sans CJK SC Regular，来自 https://github.com/notofonts/noto-cjk/tree/main/Sans/OTF/SimplifiedChinese ，遵循 SIL Open Font License 1.1。原许可随字体保存在 `Assets/LastLight/Resources/Fonts/OFL.txt`。不能将字体本身单独销售。
- **Unity 引擎及官方包**：Unity 6.0.62f1、URP 17.0.3、Input System 1.11.2、uGUI 2.0.0；各自许可适用。源代码包不包含 Unity Editor。
- **NPC Director**：使用用户已有项目的 0.3.0 后端包。本工程交付依赖副本用于本地运行，不替该项目重新授予公开发布许可。
- **Python/.NET 工具依赖**：使用其原始许可。本地 MockRenderer 的 UnityMock 只是本工程测试替身，不包含 Unity 引擎实现，也不能用于宣称 Unity 已验证。

发布或分发游戏时，请保留上述字体和依赖许可。


- **Blender**：用于制作，遵循 Blender 原有 GPL 许可；使用该工具不使本工程原创输出自动受 GPL 约束。源码包不分发 Blender 安装程序。
- **imageio-ffmpeg 0.6.0**：Windows 验证脚本用于将实际捕获帧编码为视频。Python 包采用 BSD-2-Clause，其所带 FFmpeg 二进制适用随包的 FFmpeg/LGPL/GPL 组件许可；只作为验证工具安装，不并入游戏 Player。
