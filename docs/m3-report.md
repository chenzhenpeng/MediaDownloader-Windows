# M3 界面与交互本机验收

日期：2026-11-04。客户端 `0.1.0.dev4`，内核 `0.1.0.m3-dev4`。协议仍为 v2，数据库仍为 v3。M0–M2 归档保留。

## 实现结果

- 队列与历史采用列表/详情布局，支持标题、平台、任务 ID 搜索及状态筛选。选中任务即可确认封面、媒体类型、数量、尺寸、时长、格式、保存位置和执行历史。
- 封面由独立内核请求、规范化后传回客户端；最多 3 张，单张响应限 2 MB，整体最多等待 5 秒。每次请求与重定向都使用地址检查，不向媒体域发送平台 Cookie；只接受受限尺寸的图像并生成 JPEG，客户端不接收远程媒体 URL。
- 下载格式依据实际内核能力呈现。当前三平台只提供当前解析格式，选择框禁用并说明原因，不显示不存在的清晰度选项。历史中的完成文件通过 Windows 默认应用打开。
- 进度显示已下载字节/总量、实际速度、预计时间或图集数量；未知总量使用不确定进度，不伪造百分比和速度。解析、保存、取消、失败和缺失文件都有文字反馈。
- 开始/重试/取消/打开/移除操作按任务状态启用。移除历史先清理属于该任务的临时文件，保留已下载作品；文件占用时重试，不提前丢弃清理记录。
- 修复解析尚未成功时的重试动作，先重新预览再确认下载；完成任务重新下载建立新任务并保留资源身份，原结果继续保留。
- 支持跟随 Windows、浅色、深色并持久保存；运行时读取 Windows 主题和对比度颜色。系统对比度主题优先，图标与文字使用对应系统色。使用 Segoe Fluent Icons/Segoe MDL2 Assets 回退和原生标题栏。
- 窄窗口折叠导航，列表/详情改为上下布局，主操作前置，设置及详情支持滚动。快捷键：Ctrl+N 新建、Ctrl+Enter 解析、Alt+1–4 导航、Ctrl+F 搜索；设置字段可经 Tab 遍历。
- 为主要输入与控件提供可访问名称；关键完成/失败状态可通过 Qt 可访问公告接口通知辅助技术。
- 设置加入并发数（下次启动生效）、工具版本和诊断导出。导出仅包含版本、任务状态、错误码及时间，排除链接、作品标题、路径、Cookie、代理和加密快照。

## 验证

`pytest tests upstream-ParseHub/test -q`：**170 passed、104 subtests passed**，无警告。`ruff check src tests scripts packaging` 通过。新增验证覆盖封面响应限额、图像规范化、地址检查失败、诊断内容、重试确认和历史删除的数据保留。

真实 Qt 键盘操作验证 Alt 导航、Ctrl+F 搜索、状态筛选、空结果禁用操作和设置 Tab 遍历。浅/深两主题、900/1280 逻辑像素宽度、四个页面，在 **100%、150%、200%** 设备像素比下分别捕获并检查。报告明确记录实际 DPR 为 1、1.5、2，使用进程级 Qt 缩放参数，没有修改系统显示设置。源码测试注入对比度颜色验证应用优先级，未修改 Windows 对比度主题。

证据：[界面与测试记录](../review/m3-ui-checks.json)。截图位于 `.local/m3/dpi100`、`dpi150`、`dpi200`。这些是本机与进程缩放验证，未替代实际多显示器切换、Windows 对比度主题及 Narrator 人工验收。

真实用户抖音样本在受限 PATH 下使用冻结内核取得 1 张封面并完成视频下载，耗时约 **4.95 秒**。输出 **17,240,754 字节**，SHA-256 与 M0–M2 一致：`3f5289db4a46fc30e9a0a0cab60db5d9ef6d3a6a2f5f09cade8e072d3540576b`。证据：[真实样本](../review/m3-live-sample.json)。冻结客户端已直接读取该任务数据库，验证真实封面与历史界面；截图 `.local/m3/frozen-real-history.png`。

冻结客户端、内核及捆绑工具自检和 E1/E2 选择：[冻结检查](../review/m3-packaged-checks.json)。最终 ZIP 新中文目录解压与默认内核发现：[归档检查](../review/m3-archive-check.json)。产物 SHA-256 与体积：[产物清单](../review/m3-artifacts.json)。E2 仍为相同代码的模拟版本，用于验证独立加载边界。

## 运行与后续

运行工作区 `run-m3.ps1`；或解压 `dist/m3/MediaDownloader-M3.zip`，启动 `MediaDownloader/MediaDownloader.exe`。完整保留旁边的 `_internal` 和 `engine` 目录。测试包未签名，当前没有正式安装器。

下一阶段 M4 完成作者更新检查、补丁重放、内核签名包与更新清单、后台下载校验、等待空闲切换及回滚。M3 没有启用自动更新或部署更新服务。

按用户要求延期干净 Windows/虚拟机验证。真实平台覆盖仍仅有一条抖音样本，其他平台真实登录与更多作品、实际高对比度/Narrator/多显示器和完整发行验证仍列入发布前验收。

设计依据：微软 [Windows 无障碍开发](https://learn.microsoft.com/en-us/windows/apps/develop/accessibility)、[对比度主题](https://learn.microsoft.com/en-us/windows/apps/design/accessibility/high-contrast-themes)、[进度控件指南](https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/progress-controls)，以及 [Qt 6.8 高 DPI 文档](https://doc.qt.io/qt-6.8/highdpi.html)。采用 Qt Widgets 实现 Fluent 原则，不宣称为 WinUI 或已获微软认证。
