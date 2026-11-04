# Windows 界面重构

日期：2026-11-04。根据用户对界面成熟度的反馈，优先重构界面，M5 安装发行工作尚未开始。客户端更新为 `0.1.0.dev6`，沿用已验证的 `0.1.0.m4-dev5` 内核；本轮没有升级解析内核或迁移用户数据库。

## 重构内容

| 区域 | 解决的问题 | 新行为 |
|---|---|---|
| 应用框架 | 页面像表单拼接，导航和内容缺少层级 | 区分导航底层与内容表面，统一 14 逻辑像素正文、间距、细边线和圆角；保留系统窗口边框与窗口管理 |
| 导航 | 普通按钮堆叠、当前项指示过重 | 透明导航项、短选中指示、任务数量、方向键导航与紧凑图标模式，设置固定在底部 |
| 新建下载 | 输入区比例失衡、下一步不清楚 | 紧凑输入卡片、粘贴/拖入链接、明确主操作、独立保存位置及真实最近保存入口 |
| 任务列表 | 空白表格、作品信息与操作分散 | 媒体缩略图和两行作品信息，状态/进度列，集中命令栏、右键与更多菜单 |
| 作品详情 | 详情过窄，窄窗口上下切分挤压操作 | 宽窗口可关闭侧栏；窄窗口以详情窗口查看，主操作始终留在命令栏 |
| 操作优先级 | 完成后仍把重新下载作为主操作 | 完成任务优先打开文件；重试/重新下载、取消、移除按状态呈现 |
| 设置 | 大表单混放日常选项、连接和技术字段 | 按外观/下载/平台连接/更新/关于分组，用设置行与展开项；工具、SHA、诊断默认收起 |
| 系统表现 | 图标不统一，深色与原生标题栏不一致 | 统一代码绘制的应用图标与多尺寸 ICO，DWM 深色标题栏，保留系统 Snap/最小化/最大化行为 |

封面按设备像素比绘制；长标题在详情中限制为两行并显示省略号，完整标题保留在工具提示和可访问名称中。不再展示内核尚不支持的禁用格式选择框。

连接错误可直接定位到该平台的设置。详情关闭状态在任务刷新后保留。空列表、无匹配结果、处理中、失败和已完成各有明确反馈。列表主操作与更多菜单会随选择和任务状态更新。

实际操作复查还发现原“打开文件”路径使用了错误的数据库列名；本轮改为按当前 attempt 查询 `relative_path`，从输出集合中选择媒体，避免先选中说明文件。已补验该流程，不实际启动外部播放器。

## 验证与截图

- 全量回归：**208 passed、104 subtests passed**，无警告；`ruff check src tests scripts packaging` 通过。
- 真实 Qt 操作覆盖 Alt/方向键导航、Ctrl+F 搜索、筛选、详情隐藏保持、窄窗口详情返回、平台设置定位、设置 Tab 遍历，以及完成任务打开媒体路径。
- 浅色/深色、900/1280 逻辑像素宽度，在 DPR 1、1.5、2 下分别验证；注入对比度系统色检查选中项、徽标、文字与进度。
- 冻结客户端启动、独立内核/工具自检及同一冻结客户端 E1→签名 E2→E1 继续通过。更新源的生产配置仍未部署。

证据：[界面检查](../review/ui-redesign-checks.json)、[冻结检查](../review/ui-packaged-checks.json)、[更新回归](../review/ui-redesign-update-check.json)、[最终 ZIP 检查](../review/ui-archive-check.json)。

视觉截图使用用户提供的公开作品封面，部分任务状态为明确标注的交互验收示例，不代表新增平台下载样本。

- 新建下载：`../.local/ui-redesign/accepted-dpi100/light-1280-page0.png`
- 下载队列：`../.local/ui-redesign/accepted-dpi100/light-1280-page1.png`
- 设置：`../.local/ui-redesign/accepted-dpi100/light-1280-page3.png`
- 深色：`../.local/ui-redesign/accepted-dpi100/dark-1280-page1.png`
- 窄窗口：`../.local/ui-redesign/accepted-dpi100/light-900-page1.png`
- 最终冻结客户端、真实完成记录：`../.local/ui-redesign/frozen-real-history.png`（读取隔离的数据库副本，作品与下载结果来自此前已验证的公开样本）

## 运行

工作区运行 `run-ui.ps1`；或解压 `dist/ui/MediaDownloader-UI.zip` 后启动 `MediaDownloader/MediaDownloader.exe`。完整保留 `_internal` 和 `engine` 目录。产物哈希与体积见 [清单](../review/ui-artifacts.json)。旧 M4 包继续保留，便于对比。

这是可运行的界面重构测试版。视觉重构和自动化测试不能代替真实产品体验或发行验收；实际 Windows 对比度主题、Narrator、多显示器及干净机测试继续保留为发布前工作。当前采用 Qt Widgets 实现 Windows 设计原则，不是原生 WinUI 3 控件，也不宣称已通过微软认证。

设计依据：[Windows 设计基础](https://learn.microsoft.com/en-us/windows/apps/design/basics/)、[导航](https://learn.microsoft.com/en-us/windows/apps/design/basics/navigation-basics)、[层级](https://learn.microsoft.com/en-au/windows/apps/design/signature-experiences/layering)、[设置页指南](https://github.com/MicrosoftDocs/windows-dev-docs/blob/docs/hub/apps/design/app-settings/guidelines-for-app-settings.md)、[Win32 深浅主题](https://learn.microsoft.com/windows/apps/desktop/modernize/apply-windows-themes)。
