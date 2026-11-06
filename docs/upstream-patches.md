# 历史源码回归基线

> 本文只说明开发树的历史补丁。0.3 发布客户端使用未修改的官方 ParseHub wheel，组件更新不重放这些补丁。开发测试仍保留该基线；当前架构以 [组件说明](components.md) 为准。

基线：ParseHub `75a99d6fc46e15c4b994d5245ea4518404088c99`。
历史内核构建版本：dev5（M4）；上游源补丁沿用 M1。改动位于 `upstream-ParseHub/src`，不得当作未修改的上游快照。M2–M4 新增内容位于应用 worker、任务和更新服务中。

M4 已将源代码及 Windows 测试改动导出到 `patches/parsehub` 的四组补丁，`patchset.json` 固定基线 SHA、文件范围和补丁 SHA-256；13 个重放文件与 vendored 代码等价，重放证据由本地或 CI 生成，不随文档提交。`scripts/sync_upstream.py` 在隔离候选树中重放，冲突停止。原始上游 `uv.lock` 不作为删除补丁，应用依赖仍由根目录锁文件管理。

| 补丁 | 文件 | 原因 |
|---|---|---|
| CORE-01 | utils/downloader.py | Range 探测流式读取，只检查响应头 |
| CORE-04 | types/result.py | 多文件回调关键字参数、取消清理、原子独占目录 |
| CORE-05 | utils/downloader.py | Windows 保留文件名、控制字符与尾随点过滤 |
| CORE-02 | parsers/base/ytdlp.py | 显式工具路径、冻结模式拒绝递归启动、Windows 隐藏控制台 |
| CORE-03 | provider_api/bilibili.py、parsers/parser/bilibili.py | 贯穿视频 Cookie 和 yt-dlp Netscape Cookie 转换 |

升级上游时逐项检查是否已被作者吸收，并用行为测试验证后移除重复补丁。早期 review/reproduce_findings.py 记录的是修改前的缺陷，修复后不再作为通过标准。

测试兼容补丁：B 站 FakeBiliAPI 接受新增 cookie 参数；CLI 输出路径使用 pathlib 按宿主平台断言；POSIX chmod 权限断言限定在 POSIX，Windows 桌面凭据以独立 DPAPI 测试验证。

M1 新增：

- ParseHub 可显式注入解析器列表；parser 包公开导出改为惰性加载，桌面只加载所需的一个平台。
- BaseParser 短链 HTTP 客户端增加可注入请求检查和重定向次数上限；桌面提供对应平台的地址策略。
- 下载器增加可注入请求检查、明确连接/读取超时；非重试状态不重复重启分片下载，磁盘满和权限错误不尝试其他 CDN。
- fallback 保留包装异常的原始 cause，供应用层分类，不向用户导出原始异常文本。
- 工具失败增加 ToolExecutionError 类型，yt-dlp socket/retry 参数设定明确边界。
- B 站 Cookie 改用实例级 HTTPX Cookie jar，保留用户登录态同时使用新指纹，消除已验证路径的 per-request Cookie 弃用警告。
- Windows 文件名用 PureWindowsPath 保留名规则补齐 CONIN$/COM¹ 等情形。
