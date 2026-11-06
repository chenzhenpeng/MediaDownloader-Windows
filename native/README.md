# Windows 原生客户端

WinUI 3 界面位于 `MediaDownloader`，通过私有 JSON stdio 与冻结 Python 后端通信。调度、数据库和凭据留在后端，解析在隔离 Worker 中执行。

构建、测试入口见 [贡献指南](../CONTRIBUTING.md)，组件边界见 [组件架构](../docs/components.md)。项目固定 x64；SDK 与包版本由 `global.json`、工程和锁文件管理。

`build_native.py` 负责原生前端、冻结后端及已验证执行组合的装配。`check_native_bridge.py` 验证桥接，原生布局和独立安装验收需要 Windows 桌面。生成证据保存在忽略的 `review` 目录，不提交临时验收文档。
