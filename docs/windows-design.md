# Windows 桌面界面实施规范

用户要求：遵循微软推荐的 Windows 设计。

2026-11-04：根据用户反馈重新实施界面，当前规范与截图以[界面重构报告](./ui-redesign.md)为准。此前基础窗口/主题测试不作为“成熟产品界面”的结论。

参考微软官方文档（2026-11-03 查阅）：

- [Windows 应用设计](https://learn.microsoft.com/en-us/windows/apps/design/)
- [NavigationView](https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/navigationview)
- [Windows 字体与排版](https://learn.microsoft.com/en-us/windows/apps/design/signature-experiences/typography)

本项目使用 PySide6 Widgets，采用 Fluent 的视觉和交互原则；不是 WinUI 控件实现，也不声称已经通过微软设计或无障碍认证。

当前实现：

- 保留 Windows 原生窗口边框、标题栏、调整大小和窗口管理，不绘制仿标题栏。
- 持久左侧导航，四个顶层入口；设置靠下，当前页有文本、背景和竖向指示。
- 正文使用 14 逻辑像素，优先 Segoe UI Variable Text/Segoe UI，中文提供 Microsoft YaHei UI 回退；系统图标使用 Segoe Fluent Icons/Segoe MDL2 Assets。
- 页面边距 32 逻辑像素，组件间距以 4/8 像素为基础；页面标题 28 像素、分区标题 16 像素，正文 14 像素。
- 浅色中性背景、白色内容卡片、4/8 像素圆角；主操作强调色，避免把每个按钮都设为主按钮。
- 键盘 Tab 导航、Ctrl+N 新建、Ctrl+Enter 解析，输入框有可访问名称；状态同时显示文字。
- 支持跟随系统、浅色、深色，运行时读取 Windows 个性化与对比度主题的系统颜色；对比度主题优先于手动主题。
- 搜索/状态筛选与列表/详情布局；窄窗口折叠导航并上下排列，设置和详情可滚动。
- 主要操作依状态启用，主操作前置；媒体元信息、封面、实际格式能力、进度及失败原因均有文本。
- Alt+1–4 导航、Ctrl+F 搜索；设置 Tab 遍历验证通过，关键状态提供 Qt 可访问公告。
- 100%、150%、200% 本机应用缩放验证及深浅色截图完成，设备像素比写入验收记录。
- 导航短指示与计数、任务命令栏/媒体行、窄窗口详情、设置行与渐进展开、统一应用图标和 DWM 原生标题栏主题已落地。

接下来验收：

- 实际 Windows 对比度主题切换、Narrator 和跨显示器 DPI 切换；进程注入颜色与缩放测试不作为这些实际环境验收的替代。
- M4 的更新中/等待切换/回滚结果反馈。

M3 依据补充：[微软无障碍开发](https://learn.microsoft.com/en-us/windows/apps/develop/accessibility)、[对比度主题](https://learn.microsoft.com/en-us/windows/apps/design/accessibility/high-contrast-themes)、[进度控件](https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/progress-controls)。实现与验收细节见 [M3 报告](./m3-report.md)。

不为实现半透明效果而牺牲可读性、系统兼容和窗口行为；Mica 等材质在基础行为稳定后再评估。
