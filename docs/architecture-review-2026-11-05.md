# 组件架构与更新审查

审查日期：2026-11-05。依据当前工作区实现及公开仓库发布状态；本地代码与远端部署必须分别判断。

## 判断

进程和职责分层方向合理，更新安全基础已实现；当前产品尚未达到完整的组件独立发布状态。应先完善发布与兼容选择，再扩大组件拆分。

| 层 | 当前职责 | 当前更新边界 |
| --- | --- | --- |
| WinUI 客户端 | 导航、预览、设置、下载管理 | 安装包升级；未实现客户端自动更新器 |
| Python 任务服务 | SQLite、DPAPI、队列、进程调度、更新管理 | 与客户端安装包一起发布 |
| 执行运行环境 | worker、适配层、Python 及依赖 | 随包基线或完整签名 engine 更新 |
| ParseHub | 平台解析和部分下载实现 | 完整 engine 已上线；仅 ParseHub 源码组件已有本地实现 |
| 媒体工具 | yt-dlp 下载适配、FFmpeg 合并、ffprobe 元数据 | 固定哈希，随运行环境发布；没有独立工具更新通道 |

## 应保留的设计

WinUI 通过 IPC 调用任务服务；任务服务拥有数据库和凭据，worker 执行任务。适配层封装 ParseHub 对象。下载阶段刷新地址并核对资源身份，避免长期持有过期媒体地址。候选更新经过签名、完整文件清单、大小限制、安全解包和独立进程自检；任务空闲后切换，保留 current/last_good/pending 并支持启动恢复。普通平台错误不会直接触发回滚。

## 优先修正

1. **正常更新缺少方向判断。** `UpdateManager._tick` 将任何不同 engine_version 标记为 available；防重放 sequence 仅针对以前接受的远端清单，没有以随包版本建立升级下界。本地基线 0.1.4 与远端 0.1.2 并存时，存在把旧包作为正常更新提供的路径。必须将正常升级和显式回滚分开，并定义可比较的组件发布修订号。
2. **Latest 不是组件更新目录。** `packaging/update-trust.json` 使用仓库 releases/latest/download。客户端 Release 成为 Latest 后，可能没有内核清单；新组件若只兼容部分运行环境，也会挡住其他客户端。应使用固定、签名的渠道目录，按组件、架构、运行环境和客户端协议筛选兼容候选。
3. **本地实现与线上部署脱节。** 公开 Latest 仍为 engine-0.1.2，其 engine.zip 为 316,029,096 字节；公开 main 查询 parser-release.yml 返回 404。当前小安装包不代表线上更新包也已精简。必须先发布匹配的精简运行环境，再完成 ParseHub-only 的实际签名安装、恢复、回滚验收。
4. **兼容运行环境只绑定 bundled。** `EngineStore` 为 ParseHub-only 候选校验并复用随客户端运行环境，未独立选择更新后的运行环境。当前设计安全但限制独立升级；如果要支持运行环境独立更新，需要原子记录兼容的 runtime/parser/tools 组合，不能分别切换造成混搭。
5. **适配层仍属于运行环境。** `build_parser_bundle.py` 只打包 parsehub 源码；`media_downloader.adapter` 的兼容修复不能通过该小包发布。需要明确将哪些平台兼容逻辑纳入解析组件，以及稳定的适配接口 ABI。
6. **依赖边界仍偏宽。** 根项目同时依赖 PySide6 和 ParseHub；runtime_id 从根项目依赖图计算。任务服务与 worker 的依赖锁应逐步分开，避免无关依赖变更迫使重新发布运行环境。暂不为此重写任务服务。
7. **文档和 CI 需随构建变更同步。** 原有 engine-updates.md 仍描述旧的整包方案及尚未部署状态；engine-release 工作流仍使用旧工具获取路径。上线前应对照当前媒体工具锁、精简包构建脚本和安装器重新验证，而不是将本地成功视为线上成功。

## 推荐收敛方式

用户主要看到两个更新入口：应用更新和解析能力更新。内部保留应用包、解析组件、执行运行环境三种发布单元。媒体工具先作为运行环境中的固定版本组合，不急于增加独立工具更新器；将来实测需要时再拆，FFmpeg/ffprobe 保持成对版本。

解析组件应包含 ParseHub 与明确允许更新的兼容适配代码；运行环境提供稳定协议和加载接口。签名渠道目录绑定每个候选的组件类型、发布修订、协议、架构、最低客户端和运行环境要求。下载、校验、自检和回滚统一复用现有更新管理器，不各自实现四套更新逻辑。

落地顺序：先修正常升级方向和固定更新目录；再部署当前精简运行环境；完成 ParseHub-only 发布、安装和回滚闭环；随后统一版本信息、构建文档和依赖边界。无需重写现有原生客户端。

## 证据

- `src/media_downloader/update_manager.py`：候选判断、空闲切换及回滚。
- `src/media_downloader/update_store.py`：签名安装、指针恢复、兼容运行环境选择。
- `src/media_downloader/parser_runtime.py`、`scripts/build_parser_bundle.py`：源码组件加载及运行环境契约。
- `src/media_downloader/update_archive.py`、`update_contracts.py`：文件清单、解包和签名约束。
- `packaging/update-trust.json`、`.github/workflows/engine-release.yml`、`parser-release.yml`：更新入口和发布工作流。
- 公开发布：https://github.com/chenzhenpeng/MediaDownloader-Windows/releases/tag/engine-0.1.2

本审查没有修改在线更新源或发布任何新的线上组件。
