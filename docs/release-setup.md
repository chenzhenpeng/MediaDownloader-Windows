# 线上内核发布配置

仓库： https://github.com/chenzhenpeng/MediaDownloader-Windows

- 签名算法：Ed25519，公钥 ID 为 `release-1`，公钥随客户端固定发布。
- 私钥仅配置在 GitHub `engine-release` Environment Secret；环境限制到 `main` 分支。没有开放 PR 审批权限。
- 本机恢复副本为 `.local/release-admin/engine-release-1.dpapi`，使用当前 Windows 用户 DPAPI 加密，未提交到 Git。它依赖该 Windows 用户的密钥，不是跨机器通用备份。
- FFmpeg 构建依赖由固定 HTTPS 地址和 SHA-256 校验；来源与许可记录随工具发布。
- 稳定发现入口为本仓库 Latest Release 的 `release.json` 和 `release.sig`，内核 ZIP 使用不可变的 `engine-<version>` 标签。
- 完整客户端和工具发布必须使用 `--latest=false`，以免占用内核发现入口。

## 发布过程

1. 定时检查上游，重放补丁，审查候选和依赖。没有自动合并。
2. 默认分支手动运行 `engine-release.yml`，传入新版本及大于当前公开清单的 sequence。
3. 无私钥任务运行测试、冻结构建和自检；签名任务再读取环境 Secret，创建草稿 Release。
4. 从草稿下载附件，校验签名、SHA-256、文件清单，执行真实内核自检。
5. 公开为 Latest，再运行 `scripts/check_online_engine.py`，通过冻结后端检查真实 HTTPS 下载、校验、安装、切换与回滚。验收使用独立目录，不更改用户任务。
6. 客户端手动检查或启用自动检查；安装等待当前任务结束，失败保留旧内核。

## 下载传输

客户端先请求有界 Range，支持时最多并发 4 个 4 MiB 分段并按顺序落盘。每段验证 Content-Range 和长度，完整 ZIP 仍必须通过签名清单的 SHA-256 与文件清单验证。服务器不支持 Range 时保留整包流式回退。

## 清单有效期

签名清单有效期为 30 天。`engine-feed-renew.yml` 每周一北京时间 10:23 检查现有已签名清单，递增 sequence 并续期；不会重打包、替换内核 ZIP 或更新解析代码。首次启用需实际手动执行验证。

因此下一次内核发布应使用**当时 Latest 清单中的 sequence + 1**，不要把某个固定数字写死。清单和签名两个附件替换期间，检查可能短暂失败；客户端不会安装未经验证的内容，稍后重试即可。

## 密钥与包边界

内核包签名用于验证维护方、内容完整性、版本兼容和防重放。它不等同于 Windows Authenticode；当前预览 MSI 与 EXE 尚未做产品代码签名。

旧预览客户端未配置该公钥，需要安装预览版 5 或以后版本才能直接使用线上更新。后续公钥撤销或轮换仍通过可信完整客户端更新，远端不能自行授予新公钥。

干净机及全部平台在线样本验收仍未完成。发布链路验收不代表所有平台均解析成功。
