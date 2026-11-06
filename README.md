<p align="center"><img src="native/MediaDownloader/Assets/AppIcon.png" width="72" alt="Media Downloader"></p>
<h1 align="center">Media Downloader</h1>
<p align="center">Windows 原生媒体下载工具 · WinUI 3 · ParseHub</p>
<p align="center"><a href="https://github.com/chenzhenpeng/MediaDownloader-Windows/releases/latest">下载安装</a> · <a href="docs/user-guide.md">使用说明</a> · <a href="https://github.com/chenzhenpeng/MediaDownloader-Windows/issues">问题反馈</a> · <a href="CONTRIBUTING.md">参与开发</a></p>

粘贴作品链接或分享文案，预览解析结果，再将视频、图片、图集、音频和图文保存到电脑。解析能力来自 [ParseHub](https://github.com/z-mio/ParseHub)，客户端负责下载管理、文件归档与组件更新。

## 下载与安装

前往 **[最新应用版本](https://github.com/chenzhenpeng/MediaDownloader-Windows/releases/latest)**，下载附件中以 `win-x64-Setup.exe` 结尾的安装程序。`SHA256SUMS.txt` 用于校验文件。

- 当前为 **0.3.0 Preview 1**，适合体验和反馈，尚非稳定版。
- Windows x64，建议 Windows 11；工程最低目标为 Windows 10 1809，旧系统尚未完成全面实机验证。不提供 x86 / ARM64 安装包。
- 按当前用户安装，自带所需组件，无需预先安装 Python 或 FFmpeg。完整离线安装包约 **146 MiB**。
- 预览安装程序尚未进行 Windows 产品代码签名。
- 0.3 使用新数据目录，旧设置、Cookie 和任务不迁移；已有下载文件保留。

Release 中标有“组件”或“更新渠道”的发布由应用自动使用，**无需手动下载**。

## 主要功能

- **先预览，再下载**：识别分享文案中的链接，一次提交多个作品，展示解析流程和结果。
- **统一下载管理**：查看进行中、已完成和失败任务，重试、打开文件或定位文件夹。
- **按作品归档**：按平台和作品创建目录，图集保持原帖顺序，图文可保存为 Markdown。
- **Windows 原生界面**：WinUI 3，支持浅色、深色及跟随系统主题。
- **平台连接设置**：按平台配置 Cookie 和代理；Cookie 在本机加密保存，默认隐藏。
- **独立组件更新**：ParseHub 官方包单独更新；Worker、Python 环境和媒体工具仅下载变化部分，验证后切换，失败回滚。
- **本地媒体工具**：使用自带 FFmpeg / ffprobe，或在设置中指定本地 x64 工具目录。

## 平台与文件类型

当前接入 24 个平台：

哔哩哔哩、抖音、小红书、快手、微博、知乎、百度贴吧、今日头条、微信公众号、微信视频号、酷安、豆瓣、Bangumi、小黑盒、皮皮虾、最右、YouTube、TikTok、Instagram、Facebook、X / Twitter、Threads、Snapchat、Medium。

可处理类型包括 **视频、图片 / 图集、音频、文本、图文 / Markdown**，具体以所选 ParseHub 版本和作品预览为准。接入目录不代表全部平台均已完成在线验收。登录状态、网络、地区及平台接口变化可能影响结果；带登录凭据的视频号下载仍待完整验证。

查看 [平台能力与已知限制](docs/platforms.md)。

## 快速开始

1. 安装并启动，在“设置”中选择保存位置；需要登录的平台在“平台连接”中配置。
2. 打开“新建下载”，粘贴链接或分享文案，点击“解析并预览”。
3. 确认解析结果，点击“开始下载”。
4. 在“下载管理”中查看进度、重试或打开文件。

遇到问题请先阅读 [常见问题](docs/user-guide.md#常见问题)。反馈时附版本、平台、公开作品链接与错误码，**请勿提交 Cookie、Token 或含凭据的日志**。

## 项目文档

| 文档 | 内容 |
| --- | --- |
| [使用说明](docs/user-guide.md) | 安装、连接设置、下载和常见问题 |
| [平台能力](docs/platforms.md) | 文件类型与验证边界 |
| [贡献指南](CONTRIBUTING.md) | 环境、测试、构建与提交 |
| [组件架构](docs/components.md) | 五个发布单元与更新机制 |
| [发布维护](docs/releasing.md) | 命名、Actions 与更新渠道 |
| [更新记录](CHANGELOG.md) | 面向用户的版本变化 |

## 许可与致谢

本项目自有代码采用 [MIT 许可证](LICENSE)。感谢 [ParseHub](https://github.com/z-mio/ParseHub)、[Windows App SDK](https://github.com/microsoft/WindowsAppSDK)、[Python](https://www.python.org/)、[FFmpeg](https://ffmpeg.org/) 和 [yt-dlp](https://github.com/yt-dlp/yt-dlp)。

第三方源码、依赖和随包工具保留各自许可证，不因本项目采用 MIT 而改变。详见 [第三方说明](THIRD_PARTY_NOTICES.md)。
