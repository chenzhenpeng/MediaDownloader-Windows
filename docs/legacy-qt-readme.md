# Media Downloader for Windows

基于 ParseHub 的 Windows 桌面下载器，当前为中文界面修订版 `0.1.0.dev12`，内核 `0.1.0.localized-dev12`。界面仍使用 Qt Widgets，视觉细节尚待改进。

## 运行

工作区已建立 Python 3.12 虚拟环境，可执行：

```powershell
.\run.ps1
```

或者直接运行 `.venv\Scripts\pythonw.exe -m media_downloader`。重新配置环境时执行 `uv sync --locked`。

已修复快手短链误将 M3U8 保存为 MP4 的问题，并校正时长单位；实测与更新说明见 [快手修复记录](docs/kuaishou-fix.md)。

历史时长、无效旧文件状态和四页界面已按截图审查修正，见 [修复记录](docs/screenshot-fixes.md)。

本轮统一加载 Qt 中文资源，修正右键菜单与确认弹窗语言、紧凑布局及视频号凭据提示，见 [中文界面修订](docs/localized-ui.md)。

## 当前实现

- Fluent 风格导航、中文系统字体、原生标题栏、键盘操作及 DPI 自适应。
- 新建下载、队列、历史、设置四个页面；搜索筛选、封面/媒体详情、完整进度与任务操作。
- 浅色/深色/跟随系统、对比度系统色、窄窗口布局、键盘导航及诊断导出。
- 多链接输入、ParseHub 真实解析接口、确认后重新解析并下载。
- 新下载按“平台／帖子标题与短编号”归档，图集保留顺序；旧文件不迁移、不覆盖。
- 常驻独立 worker 池、最多两项并发、心跳监测、协作取消及 Windows Job Object 兜底。
- SQLite 任务与每次执行历史、迁移备份、崩溃恢复、提交令牌及文件 SHA-256 核验。
- Ed25519 内核包验证、后台安装与自检、任务空闲切换、失败恢复、回滚与版本锁定。
- 任务去重、平台限流冷却、任务专属临时目录清理、DPAPI 加密分享链接/Cookie/代理快照。
- Range 探测、回调、Windows 文件名、B 站视频 Cookie 等内核兼容补丁。

当前接入固定上游版本的全部 24 平台入口，支持视频、图片／图集、音频与图文正文（各平台类型不同）；完整清单与验证边界见 [平台接入记录](docs/platforms-integration.md)。平台在线样本成功率尚未完成验收；没有正式安装器和已部署生产更新源。真实辅助技术/多显示器及发布验收仍按计划继续开发。

当前优先修正字体、图标和对齐，并动态展示当前内核的支持范围。最新测试包为 `dist/localized/MediaDownloader-LOCALIZED.zip`，完整解压后运行 `MediaDownloader/MediaDownloader.exe`。已重做导航、输入、任务命令栏与详情、设置行和原生标题栏主题，详见[界面改版](docs/ui-redesign.md)。M5 尚未推进；旧 M4 包保留。

M4 本机签名更新链路继续可用，同一新版冻结客户端已再次完成 E1→签名 E2→E1。生产来源默认未配置，维护端工作流尚未部署，详见 [M4 报告](docs/m4-report.md)和[发布配置](docs/release-setup.md)。干净机验证继续延期。

M0 已提供本地验证 ZIP：`dist/m0/MediaDownloader-M0.zip`，解压后可直接运行客户端；工作区也可执行 `run-m0.ps1`。这是未签名测试归档，尚非正式安装器。用户提供的 1 条抖音样本已在源码和冻结版完整下载，更多样本与干净机验收仍待完成，详见 [M0 报告](docs/m0-report.md)。

## 验证

```powershell
.venv\Scripts\python.exe -m pytest tests upstream-ParseHub/test -q
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m media_downloader --smoke-test .local/main-window.png
```

测试包含离线平台回归、DPAPI、受控本地 HTTP 实际下载和独立 worker 取消；本地 provider 仅存在于 tests，不伪装为平台在线验证。

应用数据默认存储在 `%LOCALAPPDATA%\MediaDownloader`。测试可通过 `MEDIA_DOWNLOADER_DATA_DIR` 指定独立目录，不建议多个进程共用同一测试数据库。

## 文档

- [统一开发计划](docs/development-plan.md)
- [架构设计](docs/design.md)
- [内核更新设计](docs/engine-updates.md)
- [Windows 界面规范](docs/windows-design.md)
- [界面重构与验收](docs/ui-redesign.md)
- [本地内核补丁](docs/upstream-patches.md)
- [开发进度](docs/progress.md)
- [M1 验收报告](docs/m1-report.md)
- [M2 验收报告](docs/m2-report.md)
- [M3 验收报告](docs/m3-report.md)
- [M4 验收报告](docs/m4-report.md)
- [更新源与发布环境配置](docs/release-setup.md)

上游 ParseHub 的许可保留在 `upstream-ParseHub/LICENSE`；正式发行前完成依赖 notices 清单。
