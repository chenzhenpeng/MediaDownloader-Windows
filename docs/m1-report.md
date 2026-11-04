# M1 内核兼容与修复验收

版本：客户端 0.1.0.dev2；内核 0.1.0.m1-dev2；上游仍固定在 `75a99d6fc46e15c4b994d5245ea4518404088c99`。

阶段结论：本机工程验收通过。按用户要求继续开发，未执行 Hyper-V 或干净 Windows 环境验收；平台样本覆盖仍列入发布前待验收，不将其标记为通过。

## 工作项

| 工作项 | 结果 |
|---|---|
| CORE-01 Range 探测 | 流式头部探测，忽略 Range 的大响应不完整读入内存；403 分片不重启整个下载 |
| CORE-02 工具启动 | 独立冻结内核调用捆绑工具，显式 socket/retry 边界，工具失败有类型与错误码 |
| CORE-03 B 站 Cookie | API/yt-dlp 凭据链路保留；HTTPX 使用实例 Cookie jar，刷新指纹；本机契约测试通过，真实登录待样本 |
| CORE-04 回调、取消和错误链 | 回调参数透传，取消清理独占目录；fallback 保留 cause，磁盘错误不再盲试其他 CDN |
| CORE-05 Windows 文件 | 保留名含 CONIN$/COM¹；扩展名与目录归属校验；重复目录/文件名纳入路径预算 |
| CORE-06 平台清单 | B 站/抖音/小红书按需加载，可选 SDK 故障隔离；精确入口域名与短链逐跳检查 |
| CORE-07 应用契约 | Preview/MediaInfo/Capability 与稳定错误码；重新解析后核对资源 ID，避免静默换作品/格式 |
| CORE-08 进度 | bytes/count/percent 分离；未知值为 null；只有真实字节进度计算速度/剩余时间 |

详细接口、网络限制和错误说明见 [M1 内核契约](./m1-contracts.md)。网络检查不是系统网络沙箱，DNS 地址固定和外部工具网络策略仍是发布前专项项。

## 验证证据

- 全量回归：144 passed、104 subtests passed，无警告；包括上游离线测试与应用集成测试。
- Ruff：src/tests/scripts/packaging 检查通过。
- 旧数据库：schema 1 升级到 2，仅增加 error_code，旧加密 source 和任务数据保留。
- 独立模块：测试故意阻断 SignerPy/xhshow，B 站解析器仍可加载；单个平台导入异常不会禁用其他平台。
- 网络：阻止仿冒域名、异常端口、本地/私网地址和跨平台短链跳转；测试逐跳检查及当前 Windows Fake-IP 网络兼容。
- 冻结：捆绑工具和本地媒体自检通过，同一 UI 的 E1/E2 独立内核目录握手通过；E2 仍为同代码合成版本，不是签名更新验收。
- 归档：新中文目录解压后，客户端不传 --engine-dir 也能发现并启动内核，见 [归档检查](../review/m1-archive-check.json)。

## 用户抖音样本

仍是 M0 提供的同一个独立样本，不重复计数。

- 最终 M1 冻结版在受限 PATH 下完成预览、重新解析、完整下载和提交，耗时 6.125 秒。
- 文件 17,240,754 bytes，SHA-256 为 `3f5289db4a46fc30e9a0a0cab60db5d9ef6d3a6a2f5f09cade8e072d3540576b`，与 M0 一致。
- 新预览契约输出 video/mp4、576×1024、92.9 秒，无 CDN 签名地址或凭据。
- 当前 DNS 返回 198.18.x.x；最初的新地址检查误拦截，已加入经独立公共域名 DNS 映射确认的 Fake-IP 兼容并通过真实复测。私网 IP 字面量和普通局域网目标仍拒绝。
- [脱敏样本记录](../review/m1-live-sample.json)。

## 构建与产物

- [M1 ZIP](../dist/m1/MediaDownloader-M1.zip)：367,643,234 bytes，约 350.61 MiB，未签名本地测试包。
- SHA-256：`c4a6cde73f1e61707b3429d04914e013e5b06ddb4bb1c821d34f7a8b2b6139a6`。
- [工作区启动脚本](../run-m1.ps1)，或解压 ZIP 后运行 MediaDownloader/MediaDownloader.exe。
- [构建哈希和体积](../review/m1-artifacts.json)、[冻结与双内核检查](../review/m1-packaged-checks.json)。

本次单次本机测量：内核描述命令约 0.563 秒、峰值工作集 72.48 MiB；媒体自检约 2.218 秒、峰值 84.46 MiB。不是严格冷启动或多进程总内存基准。M0 ZIP 和既有报告保留，不覆盖。

## 后续阶段

下一阶段为 M2：持续 worker 生命周期、协作取消、attempt 历史、队列去重和限流、迁移/恢复/清理策略。M1 已保留版本、资源 ID、进度、错误与 seq 契约供任务服务使用。

干净 Windows 环境、B 站真实登录、小红书/更多抖音样本、DNS/工具网络边界及正式分发许可均保留在发布前验收清单；签名内核更新和自动上游同步仍属于 M4。
