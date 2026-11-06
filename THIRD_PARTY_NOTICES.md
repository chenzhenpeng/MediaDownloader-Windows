# 第三方说明

根目录 MIT 许可证适用于本项目自有代码，不替代第三方许可证。本文件是组件索引；具体版权、许可文本和构建信息以各组件随附文件为准。

| 组件 | 用途 | 许可与来源 |
| --- | --- | --- |
| ParseHub | 平台解析 | MIT；[上游](https://github.com/z-mio/ParseHub)、[保留声明](upstream-ParseHub/LICENSE) |
| Windows App SDK / .NET | 原生界面与运行支持 | 各发行包随附许可；[Windows App SDK](https://github.com/microsoft/WindowsAppSDK)、[.NET](https://github.com/dotnet/runtime) |
| Python | Worker 环境 | [Python 许可](https://docs.python.org/3/license.html)，随包保留 |
| PySide6 / Qt | 后端 QtCore 与开发界面 | LGPL / GPL / 商业许可选项，以所用发行包随附许可为准；[Qt for Python](https://doc.qt.io/qtforpython-6/licenses.html) |
| FFmpeg / ffprobe | 媒体探测与合并 | 当前 Gyan essentials 构建保留 GPL 许可与构建说明；[来源](https://www.gyan.dev/ffmpeg/builds/)、[FFmpeg](https://ffmpeg.org/legal.html) |
| yt-dlp 与其他 Python 依赖 | 上游 SDK 依赖 | 各 wheel 的 dist-info 许可文件；[yt-dlp](https://github.com/yt-dlp/yt-dlp) |

依赖版本及摘要见 `uv.lock`、`packaging/official-runtime.lock`、`packaging/official-python.json`、`packaging/media-tools-lock.json` 和原生工程 `packages.lock.json`。安装包保留 Python 依赖许可和媒体工具 notices。分发工具时须同时检查对应构建的源码提供要求。

开发树中的 `upstream-ParseHub` 含历史回归补丁；发布客户端使用未修改的官方 wheel，区别见 [贡献指南](CONTRIBUTING.md)。
