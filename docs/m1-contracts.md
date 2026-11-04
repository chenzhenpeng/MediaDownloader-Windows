# M1 内核适配契约

当前实现：客户端 0.1.0.dev2，内核 0.1.0.m1-dev2。保持 IPC protocol=1；新预览、错误、进度和 seq 为增量字段。旧 M0 包保持独立，不被此次构建覆盖。

## 解析器与上游隔离

应用层只有 adapter.py 负责选择解析器和转换上游结果，UI 不直接处理 ParseResult。ParseHub 可通过 parsers 参数显式注入列表，旧的默认注册行为仍保留给库/CLI。

支持候选清单为 bilibili/douyin/xhs。每次解析只导入目标平台；--describe 独立探测各平台并输出 available/error_code。某个平台的可选 SDK 缺失或导入失败只使该平台不可用，不代表其他平台失败。

能力状态统一为 experimental。当前仅提供当前解析结果，format_selection=false，不伪造 4K/音轨/字幕选项；LivePhoto 没有完成样本覆盖，live_photos=false。available 只表示组件可加载，不是线上成功率声明。

## 预览与资源一致性

Preview 包含 title、platform、resource_id、media_type、media_count、media 和 capability。

media 项只包含 kind、extension、width、height、duration_seconds；未知值为 null，不向 UI/数据库导出 CDN 签名 URL 或 Cookie。抖音 API 毫秒转为秒；缺失/非有限时长归为未知。

resource_id 为不含敏感参数的资源标识哈希。识别抖音 video/note/slides ID、小红书条目 ID、B 站视频 ID 与分 P。相同作品不同跳转域名不误判为变化，B 站不同分 P 仍区分。

下载命令传入预览的 expected_resource_id。重新解析发现资源变化或格式选择不可满足时，返回 RESOURCE_CHANGED/FORMAT_UNAVAILABLE，不静默替换用户确认的对象。

## 进度

| kind | 可用字段 | 约定 |
|---|---|---|
| bytes | completed_bytes、total_bytes、speed_bps、eta_seconds | 只有实际字节流才计算速度 |
| count | completed_items、total_items | 图集按完成文件数，字节和速度留空 |
| percent | percent | yt-dlp 原上游百分比不会冒充 bytes |

所有类型含 phase 和可空 percent。每秒最多约 5 次进度事件，完成事件不被节流。未知总量不伪造总大小/剩余时间；重试回退时重置速度时间基线。

worker 事件带 attempt_id 和单调 seq。当前客户端拒绝旧 attempt 和重复/倒序 seq；无 seq 的旧 protocol=1 消息按兼容路径处理。

## 错误

错误事件包含 code、message、action、retryable、phase，允许持久化错误码。UI 详情展示中文提示和错误码，不显示上游异常原文。

典型分类：UNSUPPORTED_URL、PLATFORM_UNAVAILABLE、CORE_DEPENDENCY_MISSING、AUTH_REQUIRED、AUTH_EXPIRED、CONTENT_UNAVAILABLE、ACCESS_DENIED、RATE_LIMITED、NETWORK_TIMEOUT、NETWORK_ERROR、TOOL_MISSING、TOOL_FAILED、DISK_FULL、PERMISSION_DENIED、PATH_TOO_LONG、FORMAT_UNAVAILABLE、RESOURCE_CHANGED、UNSAFE_URL、UNSAFE_REDIRECT、INCOMPLETE_DOWNLOAD、SAVE_FAILED。

分类遍历 cause/context 与 fallback 尝试链，有循环和数量限制。磁盘错误等不能被备用 CDN 包装成无关的普通网络错误。未知失败返回固定中文提示，不包含源 URL、服务器响应、Cookie、代理密码或工具尾部日志。

SQLite 从 M0 schema 1 原地增加 error_code 并更新为 schema 2，不重建任务表、不解密重写旧 source。完整迁移备份和 attempt 历史仍属于 M2。

## 网络和文件边界

- 入口精确匹配支持平台 hostname，拒绝用户信息、异常端口、仿冒域名和非法 URL。
- 短链每次 HTTPX 跳转仍须属于原平台；媒体 HTTPX 请求检查协议、目标地址及每次重定向，拒绝本地/私有地址。
- 兼容 Windows TUN 代理的 198.18.0.0/15 Fake-IP：只有目标主机和固定公共哨兵域名均出现该映射时才接受 DNS 映射；IP 字面量、localhost、普通局域网地址依然拒绝。这个探测不发 HTTP 请求。
- 媒体连接 10 秒、读取 30 秒；解析入口总时限 120 秒；HTTPX 最多 10 次重定向。yt-dlp socket 和重试次数有显式边界。
- 非重试状态/磁盘故障不重复整个分片下载；每个任务拥有独立工作目录，目录独占创建。
- 文件扩展名限定为短字母数字；Windows 保留名、尾随点/空格和控制字符被处理。工作目录与文件名重复使用的长度纳入预算，超长位置提示更换目录。
- 保存完成前要求文件非空、真实路径属于本任务工作目录；最终目录仍经客户端提交授权。

这些是当前 HTTPX 路径的应用检查，不是系统网络沙箱：DNS 预检查与实际连接之间尚未做地址固定，外部 yt-dlp/provider 内部连接没有统一的 DNS/IP 强制策略。DNS 重绑定、代理远端解析和工具层网络边界保留为发布前专项验收，不将本机成功解释为完整防护证明。

## 验证方式

M1 回归覆盖可选依赖隔离、错误脱敏、进度真实语义、资源一致性、短链逐跳拦截、Fake-IP、旧数据库升级、403 分片停止重试、磁盘满停止备用链接和 Windows 文件名/长度。

工程阶段在本机验收；按用户要求，干净 Windows/虚拟机验证延期。真实平台覆盖仍只有此前用户提供的 1 条抖音短链，B 站真实登录和小红书覆盖仍需后续样本，不宣称这些平台已发布稳定支持。
