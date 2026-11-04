## 当前 x64 MSI（预览版 5）

`MediaDownloader-0.2.0-preview.5-win-x64.msi` 使用 WiX 6.0.2 构建，MSI Template 为 `x64;2052`，2535 个组件均为 64 位组件。应用、后端和内核也是 x64。

安装目录写入当前用户注册表，维护修复和卸载读取同一路径，避免自定义目录回退到默认位置。

已在隔离 QA 产品上验证安装后启动、Cookie 掩码回显、修复保留数据、卸载保留用户文件和数据库。未卸载用户原有应用。当前包未进行产品代码签名，干净机验收仍待完成。

从此前 EXE 安装版迁移须先手动卸载旧应用，再安装 MSI；用户数据及下载作品保留。后续 MSI 使用固定 UpgradeCode 升级。

以下为此前 EXE 安装方案的历史记录。

# Windows 安装版

当前产物：`dist/release/MediaDownloader-0.2.0-preview.3-win-x64-Setup.exe`。
这是本地可安装的预览 Release，尚未上传到远端，也没有产品代码签名。

## 用户体验

- 全中文安装与卸载向导；仅安装到当前用户，不申请管理员权限。
- 自带 .NET、Windows App SDK、Python 后端及解析内核，无需用户单独配置运行环境。
- 默认路径为 `%LOCALAPPDATA%\Programs\MediaDownloader`；提供开始菜单入口，桌面快捷方式可选。
- 程序载荷放在 `versions\<发行版本>` 内。快捷方式指向当前版本，应用与内核相对目录关系保持不变。
- 固定 AppId，覆盖安装沿用原路径及同一个卸载条目；旧版本载荷仍由卸载日志管理。
- Native 前端持有命名 mutex，安装与卸载发现应用运行时要求先退出；不强制终止下载。
- 用户数据仍在 `%LOCALAPPDATA%\MediaDownloader`，下载文件保留原位置。
- 卸载只移除安装器管理的文件、快捷方式及卸载项，不递归清空安装目录，也不删除用户数据。

安装器要求 Windows 10 build 19041 或更高版本、x64 兼容环境；本机验收环境为 Windows 11 x64。
其他系统及 ARM64 仿真尚未实机验收。当前用户安装与 MSI/MSIX 企业部署是不同的发行方式。

## 构建

1. 用 `scripts/build_native.py` 准备原生载荷。
2. 准备固定版本 Inno Setup 编译器，来源与校验值见 `packaging/windows/toolchain.json`。
3. 运行 `.venv\Scripts\python.exe scripts/build_installer.py`。

脚本检查必需文件，拒绝打入 SQLite 用户数据库和锁文件，生成逐文件 SHA256 清单，编译安装器，
再输出 `release.json` 与 `SHA256SUMS.txt`。默认编译器位于工作区缓存；可通过 `--compiler` 显式指定。
发行版本集中在安装脚本与构建脚本中，改变版本时需要同步检查客户端展示版本及发行元数据。

## 验收

运行 `.venv\Scripts\python.exe scripts/check_installer.py`，在工作区隔离目录执行首次安装、
完整文件清单校验、原生界面启动、运行保护、同版本覆盖安装、再次启动与卸载。
脚本若发现本产品已有安装会立即停止，不覆盖或卸载已有安装。
任务数据库测试标记、用户自行创建的文件在覆盖安装与卸载后都必须保留。
这是同版本覆盖验收，不能代替未来真实跨版本迁移测试。

公开稳定版之前仍需产品代码签名、跨机器验收及正式更新源部署。
本安装包仅负责完整客户端安装；解析内核继续走原有签名校验、空闲切换与回滚链路。
按用户要求没有使用 Hyper-V。


