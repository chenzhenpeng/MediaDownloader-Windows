# 参与开发

欢迎可复现的问题、文档改进和 Pull Request。先搜索已有 Issue；较大的架构改动建议先说明目标和范围。

## 环境与测试

Windows x64、Python 3.12、uv、7-Zip（`7z` 加入 PATH）、`native/global.json` 指定的 .NET SDK，以及 Windows SDK 10.0.26100。依赖版本由锁文件管理。

```powershell
uv sync --locked
uv run --no-sync ruff check src tests scripts packaging qa/official
uv run --no-sync pytest tests upstream-ParseHub/test -q --tb=short -k "not test_ui_keyboard_themes_and_responsive_layout"
```

交互式键盘与布局验收需要 Windows 桌面，不能用无桌面 CI 代替。行为变化添加针对性回归；勿提交 Cookie、下载文件和本机验收记录。

## 目录

| 目录 | 内容 |
| --- | --- |
| `native/MediaDownloader` | WinUI 3 界面与私有 stdio 桥接 |
| `src/media_downloader` | 调度、存储、凭据、更新协调器、Worker |
| `packaging` | 依赖、工具、信任和安装配置 |
| `scripts` / `tests` | 构建、发布、验收与回归 |
| `upstream-ParseHub` / `patches` | 历史源码回归基线与补丁重放 |

## 两条验证路径

- **当前发布验收（PR 必跑）**：统一构建命令获取官方 wheel 和锁定环境，`qa/official/contracts.py` 在实际随包 Python 中运行，校验官方来源、逐文件原包一致性、24 平台能力、视频 / 图集 / 实况 / 文本转换、凭据错误、作品变化以及本地 HTTP 图集真实下载和进度。另验证组件签名更新、回滚和原生编译。不会给发布环境额外安装 pytest，不使用补丁版 SDK。
- **补充应用及历史回归**：上述 pytest 命令使用开发虚拟环境及保留的源码基线。它不能代替官方包验收；历史补丁重放另放在手动工作流 `legacy-regressions.yml` 中。

两条 PR 检查都应通过。离线官方测试不代表所有平台在线可用。不要把开发虚拟环境替换到客户端中。见 [历史基线](docs/upstream-patches.md)。

## 构建

本地、PR 和发布工作流共用 `scripts/build_windows.py`。从仓库根目录执行：

```powershell
# 完整构建：同步开发依赖、获取官方组件、验收、还原 NuGet、编译并生成安装包
./build.ps1

# 只构建并验证官方执行组合，不需要 .NET SDK
./build.ps1 -Stage components

# 编译完整应用和冻结后端，不生成安装包
./build.ps1 -Stage app

# 7-Zip 没有加入 PATH 时显式指定
./build.ps1 -SevenZip 'C:/Program Files/7-Zip/7z.exe'
```

脚本自动复制工具及许可文件，跳过不需要的独立 yt-dlp EXE，使用锁定官方 wheel 和 Python，验证完整组合、签名更新与回滚，然后执行锁定的 NuGet restore 和原生构建。安装器复用前先校验编译器摘要。每次使用新的工作目录，不自动删除已有工作目录；日志末尾输出组件路径和验收报告路径。

原生输出位于 `dist/native/MediaDownloader`，安装包在 `dist/release`；应用输出会重新生成。工作目录默认在忽略的 `.local/b`，可以通过 `-WorkDir .local/my-build` 指定新的目录。重跑不依赖已有种子、工具缓存或本机私钥。

要复用一个已验收的完整组合，可指定 `-Components <组合目录>`；它仍要经过官方包和更新验收。`-QA` 额外生成独立 QA 安装器。签名和公开发布见 [发布维护](docs/releasing.md)，QA 包不能作为用户附件发布。

官方包契约检查也可单独运行：

```powershell
uv run --no-sync python scripts/check_official_contract.py --bundle <组合目录> --output review/official-contract.json
```

## 提交约定

- 说明问题、最终行为和验证方式，保持范围清晰。
- 不提交 `.local`、`.cache`、`review`、`dist`、构建输出、凭据或私钥。
- 长期文档放 `docs`；临时进度和验收记录留在本地，版本变化写入 `CHANGELOG.md`。
- 修改锁文件时注明来源，验证完整执行组合；保留第三方版权和许可证。
- 自有代码按本项目 MIT 许可提交。
