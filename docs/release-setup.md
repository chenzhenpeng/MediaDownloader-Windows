> 2026-11-04：公开源码仓库已创建为 https://github.com/chenzhenpeng/MediaDownloader-Windows 。工作流已上传；生产签名密钥、工具包变量和客户端信任源尚未配置。下文的“尚未连接远端”是此前实施记录。

# 内核更新源与发布环境配置

本地已实现签名包、验证、空闲切换、恢复与回滚，以及三份 GitHub Actions 工作流。本工作区尚未连接本项目的远端仓库，也没有生产签名密钥。这里列出启用线上发布所需的具体配置；创建这些文件不等于定时检查已在运行。

## 维护端工作流

- `.github/workflows/upstream-watch.yml`：每 6 小时及手动检查 ParseHub 默认分支，按 SHA 去重，验证补丁哈希并重放，成功后建立草稿 PR。补丁冲突保留报告并阻止后续操作。
- `.github/workflows/validate.yml`：只读权限运行 Windows 契约/上游测试、静态检查和补丁重放。依赖变化时需要在候选 PR 中重新生成并审查 `uv.lock`。
- `.github/workflows/engine-release.yml`：只接受默认分支的手动触发。先在无签名私钥的任务中构建和自检，再进入受保护的 `engine-release` 环境签名并创建草稿 Release。不会自动公开发布。

工作流依赖的官方 Actions 已固定到实际查询到的提交 SHA。候选准备任务不会导入或构建新上游代码；不使用 `pull_request_target`/`workflow_run` 执行候选并获取写权限或签名密钥。依据：[GitHub Actions 安全使用指南](https://docs.github.com/en/actions/reference/security/secure-use)。

## 仓库配置

上传代码到确定的 GitHub 仓库后：

1. 允许仓库 Actions 创建 PR；默认分支要求 PR 审查和 Windows validation 检查。
2. 建立 `engine-release` Environment，限制到默认分支并配置维护者审批。签名密钥只放在这个环境中，不放仓库文件或普通 PR 可访问的环境。
3. 配置以下变量与密钥。

| 名称 | 位置 | 内容 |
|---|---|---|
| `ENGINE_TOOLS_URL` | 仓库变量 | 经审查的 HTTPS FFmpeg 工具 ZIP 地址 |
| `ENGINE_TOOLS_SHA256` | 仓库变量 | 此 ZIP 的固定 SHA-256 |
| `ENGINE_KEY_ID` | 环境或仓库变量 | 稳定的生产公钥 ID，如 `release-1` |
| `ENGINE_SIGNING_KEY_PEM` | `engine-release` 环境 Secret | Ed25519 私钥 PEM；禁止输出或放入构建产物 |

工具 ZIP 根目录必须包含 `bin/ffmpeg.exe`、`bin/ffprobe.exe`、`LICENSE`、`README.txt`。工具来源、许可与哈希应一起审查；本项目不会在 CI 中无校验地下载“最新版”。

## 客户端信任配置

发行客户端前，将生产公钥和来源写入 `packaging/update-trust.json` 并重新构建客户端。默认文件公钥为空，因此当前测试包明确显示未配置来源，不会误报“已是最新版”。

配置示意，`OWNER/REPO` 和公钥必须替换为实际值：

```json
{
  "schema_version": 1,
  "channel": "stable",
  "keys": {"release-1": "<base64 编码的 32 字节 Ed25519 公钥>"},
  "allowed_hosts": ["github.com", "release-assets.githubusercontent.com"],
  "manifest_url": "https://github.com/OWNER/REPO/releases/latest/download/release.json",
  "signature_url": "https://github.com/OWNER/REPO/releases/latest/download/release.sig"
}
```

首版使用 GitHub Releases 托管独立内核和两份元数据。每个内核 Release 的 ZIP 地址按不可变 tag 固定；清单和签名的 latest 入口只负责发现当前稳定内核。**这个仓库的 Latest 必须留给稳定内核 Release**；后续完整客户端 Release 使用 `--latest=false`，或将内核源放入独立发布仓库。若实际 CDN 增加其他跳转域，审查后加入允许列表再发行客户端；不放开通配域名。

公钥更新/撤销通过可信的完整客户端更新完成；当前没有实现远端自授权新增公钥。生产私钥需要由维护者离线备份，本地测试使用的临时密钥不能用于生产，也不会加入默认客户端信任文件。

## 一次维护发布

1. 作者更新进入候选 PR；查看新旧 SHA、涉及的接口文件、依赖元数据与补丁应用结果。
2. 必要时解决补丁冲突和刷新锁文件，通过源码测试、Windows 冻结检查及目标平台真实样本。补丁被上游吸收时经等价行为测试后移除，不强行重复应用。
3. 合并审查后的候选。手动触发 engine-release，提供新的不可变内核版本和严格递增的 sequence。相同版本不得重新打包发布不同字节。
4. 完成受保护环境审批，检查草稿 Release 的 `engine.zip`、`release.json`、`release.sig` 和验证证据。
5. 完成干净机、许可和平台回归后，公开发布该内核 Release，并将其设为 Latest。beta 包不作为 stable Latest。
6. 客户端检查签名清单后提示更新；用户安装时下载整包、校验与自检，等待任务结束切换。失败保留旧内核，显式回滚不降低防重放 sequence。

首次发布前需在 GitHub 上实际跑通工作流和来源重定向；本机测试不能证明远端权限、Environment 审批或 Release 托管已经配置。

## 本地冻结验收

```powershell
.venv\Scripts\python.exe scripts/build_m0.py --milestone m4 --skip-tools
.venv\Scripts\python.exe scripts/check_m4_frozen.py --output .local/m4/signed-cycle-new
```

脚本生成临时测试公钥和本地签名 feed，通过显式 `--update-config` 启动隔离的冻结客户端，验证同一进程 E1→E2→E1。E2 使用相同解析代码与模拟版本字段；这是更新机制验证，不代表作者发布了新版本。`--update-smoke-test` 仅接受显式本地测试源，不会对默认生产来源自动执行安装。
