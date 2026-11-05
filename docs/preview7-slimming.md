# Preview 7 安装包精简

应用文件经过以下调整，保留全部现有平台入口与离线安装能力：

最终原生 x64 EXE 为 **137,490,891 字节（约 137.5 MB）**，比 Preview 6 的 214,409,584 字节减少 **35.87%**；同一精简程序使用 MSI 打包为 187,522,525 字节。EXE 与已通过安装验收的 QA 包使用完全相同的 876 个程序文件清单，SHA-256 清单摘要一致。正式包 SHA-256：`055505c0e189947831cc4b25e2ad040523eea4c9913c0592e7b8ccee2d028b23`。

| 项目 | 改动 |
| --- | --- |
| Windows App SDK | 用 WinUI、DWrite 组件包替代整套 SDK 引用，不再分发未使用的 Windows ML、ONNX、DirectML 组件 |
| 后台 | 保留调度器实际需要的 QtCore，排除 QtNetwork、QtGui、QtWidgets 与通用打包钩子带入的 OpenGL 软件渲染文件 |
| yt-dlp | 使用相同固定版本的官方 Windows x64 独立程序，校验发布方 SHA-256，移除重复的 Python 工具目录 |
| FFmpeg | 改用 Gyan 9.0.2 essentials 预编译版本，只携带 ffmpeg、ffprobe 与许可说明；不携带 ffplay、开发文件和完整构建的共享 DLL |
| 构建 | 每次清空已验证位于 dist/native 的生成目录，防止旧依赖遗留；审计工具哈希及禁用依赖是否重新出现 |
| 安装压缩 | Inno Setup 7.1.1 原生 x64、LZMA2 固实压缩、128 MiB 字典；同一程序也可生成 MSI |

必须区分下载压缩包与解压体积：essentials 的 7z 下载包约 35 MB，但 ffmpeg、ffprobe 解压合计约 201 MiB。因此 FFmpeg 调整本身并非解压体积的大幅下降，整体收益来自依赖清理、去除 yt-dlp 重复运行环境和压缩方式的组合。

## 安装失败的处理

截图和 Windows Installer 事件确认旧包遇到错误 1926：设置 `D:\Config.Msi` 回滚文件安全权限时访问被拒绝。没有修改该系统目录的权限，也没有禁用 MSI 回滚。

面向普通用户的新 EXE 安装器不调用 Windows Installer，不依赖 Config.Msi。采用当前用户安装方式，安装器和卸载器均已检查为 x64。旧 MSI 与 EXE 的产品注册机制不同，正式安装器检测到旧 MSI 时会要求先在 Windows 设置中卸载；任务、Cookie 与下载文件不会随程序卸载删除。MSI 另改为标准 per-machine 管理员安装模式，但该模式尚未完成提权安装验收，不作为本次推荐测试入口。

## 已执行验收

- 301 项测试、104 项子测试通过。
- 移除 SDK 与 Qt 依赖后，18 个原生窗口尺寸、主题及导航场景通过。
- 精简工具通过音视频码流合并、HLS 合并、ffprobe 信息读取与完整解码；官方 yt-dlp 从本机 HTTP 实际下载 HLS 后的文件也通过验证。
- 冻结内核在仅有系统目录的 PATH 下完成视频、图片下载自检。
- 独立身份的 EXE 测试包在普通用户权限、F 盘项目隔离目录中通过安装、876 个文件哈希校验、启动、运行中阻止安装、修复保留数据、卸载保留未知文件及数据库。

证据：`review/native/package-audit-preview7.json`、`review/media-tools-acceptance.json`、`review/native/installer-acceptance.json` 和 `build/preview7-regression.log`。

复现轻量内核时，向 `scripts/build_m0.py` 传入 `--ffmpeg-dir` 和 `--ytdlp-exe`，二者须与 `packaging/media-tools-lock.json` 中的哈希一致。构建安装器使用 `scripts/build_installer.py`；`--qa` 生成独立产品身份，`scripts/check_installer.py` 只操作该 QA 身份，拒绝操作指向其他目录的卸载记录。
