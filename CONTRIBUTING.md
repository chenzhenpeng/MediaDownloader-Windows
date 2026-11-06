# 参与开发

欢迎可复现的问题、文档改进和 Pull Request。先搜索已有 Issue；较大的架构改动建议先说明目标和范围。

## 环境与测试

Windows x64、Python 3.12、uv、`native/global.json` 指定的 .NET SDK，以及原生工程对应 Windows SDK。依赖版本由锁文件管理。

```powershell
uv sync --locked
uv run --no-sync ruff check src tests scripts packaging
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

**发布路径与开发回归基线不同。** `uv sync` 使用本地可编辑 ParseHub 基线运行既有回归；发布环境由 `build_official_runtime.py` 获取并验证未修改的官方 wheel。不要把本地补丁树作为发布 SDK，也不要用开发虚拟环境替换客户端组件。见 [历史基线](docs/upstream-patches.md)。

## 构建

完整步骤以 `.github/workflows/components-release.yml`、`application-release.yml` 为准。本地构建不需要发布私钥：

1. 运行 `scripts/fetch_media_tools.py` 获取锁定工具；按组件工作流把 FFmpeg / ffprobe 放入 `build/official-tools`，许可说明放入 `build/notices`。
2. 执行：

```powershell
uv run --no-sync python scripts/build_official_runtime.py --output dist/build-seed --version build-seed --seed-only --tools build/official-tools
uv run --no-sync python scripts/build_component_bundle.py --seed dist/build-seed --output dist/component-bundle
uv run --no-sync python scripts/build_native.py --engine-dir dist/component-bundle
uv run --no-sync python scripts/fetch_installer_toolchain.py
uv run --no-sync python scripts/build_installer.py
```

原生输出在 `dist/native/MediaDownloader`，安装包在 `dist/release`。签名和渠道见 [发布维护](docs/releasing.md)。QA 专用安装程序不能作为用户附件发布。

## 提交约定

- 说明问题、最终行为和验证方式，保持范围清晰。
- 不提交 `.local`、`.cache`、`review`、`dist`、构建输出、凭据或私钥。
- 长期文档放 `docs`；临时进度和验收记录留在本地，版本变化写入 `CHANGELOG.md`。
- 修改锁文件时注明来源，验证完整执行组合；保留第三方版权和许可证。
- 自有代码按本项目 MIT 许可提交。
