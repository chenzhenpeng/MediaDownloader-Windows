# 独立组件与执行组合（0.3 新基线）

| 发布单元 | 内容 | 更新来源 |
| --- | --- | --- |
| 应用包 | WinUI、任务服务、数据库、凭据、更新协调器 | x64 安装程序 |
| Worker | IPC、官方 SDK 适配、预览、下载处理、HLS 合并及文件提交 | 本项目签名小包 |
| ParseHub | 未修改的官方 wheel，初始 2.4.0 | 官方 PyPI，保留原版本和原包 |
| Python 环境 | Python 3.13.17、固定依赖和 Python yt-dlp 模块 | 独立签名完整环境包 |
| 媒体工具 | FFmpeg、ffprobe 和许可文件 | 独立签名工具包，或显式选择本地目录 |

Python 环境不包含 Worker 或 ParseHub。Worker 使用明确模块清单构建，不再复制整个客户端 Python 包。文件路径计算已与数据库导出模块分离，Worker 不导入 UI 或数据库。

## 组合启动与更新

初始安装的 `engine/profile.json` 引用四个独立组件目录。启动使用明确绝对路径和隔离 Python，检查 ABI、协议、版本范围、SDK 依赖与实际导入来源。

本项目组件通过 `channel-components-v1` 签名目录发现，采用协议 3。更新计划只下载发生变化的组件，安装到不可变目录，然后构造完整候选组合。依赖验证及独立进程自检成功后，等待任务空闲，原子切换一个组合指针；握手成功后确认。中断或失败恢复上一完整组合，清理保留当前和上一组合引用的组件。

官方 ParseHub 仍直接读取 PyPI，检查 wheel、固定 HTTPS 来源、大小、SHA256、归档路径、Python、依赖和 extras。不在用户机器上运行 pip 或构建代码。PyPI HTTPS+摘要和本项目 Ed25519 签名是不同信任来源，不混称为发布者签名。官方原包同样经过完整组合验证和切换。

## 本地媒体工具

设置可以选择同时包含 `ffmpeg.exe`、`ffprobe.exe` 的本地目录。检查 x64 PE、版本及 MPEG-TS/MP4 能力，记录二进制摘要，组合解析时重新检查。在线更新跳过显式选择的本地工具。外部目录不会被复制、覆盖或清理；“使用自带”会构造引用随包工具的新组合。

Python 暂只支持完整环境包，不自动修改系统 Python。yt-dlp 暂随依赖包成套管理，不能用独立 EXE 替代 SDK 使用的 Python 模块。

## 构建和发布

- `build_official_runtime.py --seed-only` 从官方 Python 和哈希锁创建构建种子，不作为客户端布局发布。
- `build_component_bundle.py` 分离组件和原始 wheel，生成离线组合并探测。
- `components-release.yml` 在 GitHub Actions 构建、签名指定的变化组件，生成独立草稿。
- `component-catalog.yml` / `component-catalog-renew.yml` 发布、续签新组件渠道。
- `application-release.yml` / `materialize_components.py` 消费三个验签组件及官方 wheel，构建完整安装包。
- `upstream-watch.yml` 只读监测官方 PyPI，不重放补丁或重新包装解析器。

完整安装包目前仍携带离线所需组件；拆分主要减少后续更新流量，初装大小不会缩至 Worker 的大小。精简安装器是后续分发选项。

## 验收与边界

393 项非交互回归和 104 个子测试通过。真实签名 Worker 测试更新包约 33 KiB，其他组件复用原目录；签名安装、重启恢复、本地工具和中断回滚均通过。原生冻结后端发现 24 个平台，快手 39 分段样本完整下载为约 296 秒且含音轨的 MP4。

不宣称所有平台均已实测，带凭据视频号仍需独立验证。HLS 当前支持有限、未加密的 MPEG-TS 清单。

新客户端使用 `%LOCALAPPDATA%/MediaDownloader/v6`，不导入旧组件、设置、任务或凭据，不删除旧数据及下载文件。旧环境不能作为新执行组合启动。
