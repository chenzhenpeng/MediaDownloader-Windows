# Windows 原生界面迁移

当前客户端：0.2.0.dev13；正式执行运行环境：0.1.5；ParseHub 上游版本：2.4.0；内核协议：2。

## 设计与实现

采用 WinUI 3、标准 TitleBar、NavigationView、Mica 和系统控件。应用名称只在标题栏出现。
正文使用系统字体与原生字号层级；页面使用 32 DIP 边距、24 DIP 卡片内边距和统一对齐。
主页把链接输入、解析按钮、保存位置放入同一个操作区；平台与文件类型放入可搜索的完整列表。
任务用紧凑列表呈现封面、标题、媒体信息、状态和当前可执行操作；完整标题在详情内可选择复制。
设置按外观、下载、平台连接和内核更新分组。输入菜单、任务菜单和确认按钮使用中文。
浅色、深色及跟随系统采用语义主题资源；弹窗跟随当前应用主题。

参考微软文档：[应用结构](https://learn.microsoft.com/en-us/windows/apps/develop/ui/windows-app-sdk-app-structure)、
[NavigationView](https://learn.microsoft.com/en-us/windows/apps/design/controls/navigationview)。

## 后端与内核更新

原生前端通过私有 JSON stdio 桥接冻结的 MediaBackend.exe。后端继续复用任务调度、SQLite、
下载校验、DPAPI 凭据存储和 UpdateManager。界面快照只返回凭据是否已保存，不返回 Cookie、代理值或加密来源。
列表每页 50 项，封面按变化传输。旧版 Qt 与新版共享数据目录并使用同一应用锁。

ParseHub 更新仍走原有独立内核流程：固定上游版本 → 应用补丁 → 构建整套内核 → 自测与兼容性检查 →
签名清单 → 客户端验证 → 空闲切换 → 失败回滚。WinUI 前端不直接导入 ParseHub，内核更新不要求重装界面。
当前测试包没有配置生产更新源，设置页会如实显示此状态。

## 构建与测试

本地 SDK 位于 `.cache/dotnet`，NuGet 使用工作区缓存。包版本固定在 csproj 与 packages.lock.json。
运行 `scripts/build_native.py` 构建原生前端、冻结后端，并复制已经验收的解析内核。
脚本显式复制应用 PRI/XBF，避免 dotnet publish 漏带页面资源。

`scripts/check_native_bridge.py` 检查冻结桥接、24 个平台能力和设置；附加 `--sample` 可验证公开作品的解析与下载。
`tests/test_native_host.py` 检查分页、凭据隔离和封面缓存范围。
验收报告与实际窗口截图位于工作区 `review/native`。

## 发布前仍需完成

这是一轮原生界面预览，尚未作为商业正式版验收。
后续需要完成多显示器/DPI、键盘与读屏、系统高对比度、窗口缩放、长时间任务和跨机器测试，
以及安装升级、代码签名、正式更新源部署。24 个平台的目录能力不等于全部平台实时下载验收通过。
按用户要求，当前没有进行 Hyper-V 或干净虚拟机验证。


