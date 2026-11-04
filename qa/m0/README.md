# M0 验收操作

真实样本保存在 `.local/m0/samples.json`，不要提交 Cookie、签名参数或私密链接。记录格式示例：

```json
[
  {
    "id": "bili-video-01",
    "platform": "bilibili",
    "category": "public_video",
    "url": "<实际公开作品链接>",
    "expected": "downloadable"
  }
]
```

platform 为 bilibili/douyin/xhs；category 记录 video/gallery/short_link/login 等具体类别；expected 为 downloadable/content_unavailable。每个首发平台至少 10 条预期可下载样本，删除/私密等预期错误单独列。

```powershell
.venv\Scripts\python.exe scripts/validate_samples.py .local/m0/samples.json --download --output .local/m0/live-run-01
```

每样本默认 120 秒、100 MiB 的本地输出预算；达到限制是未通过，不计为平台成功。需要凭据时通过本地进程环境传入 `MEDIA_DOWNLOADER_M0_COOKIE_BILIBILI` 等变量，代理为 `MEDIA_DOWNLOADER_M0_PROXY`；不要在共享命令记录中写入值。报告只记录是否使用，不写原文或完整 URL。

冻结构建及本机受限 PATH 验证：

```powershell
.venv\Scripts\python.exe scripts/build_m0.py
.venv\Scripts\python.exe scripts/check_m0.py
.venv\Scripts\python.exe scripts/check_frozen_sample.py .local/m0/samples.json --engine-dir dist/m0/media-engine --output .local/m0/frozen-live-01
```

产物位于 `dist/m0`，日志位于 `build/logs`，自检输出位于 `.local/m0`。运行 `scripts/package_m0.py` 生成包含默认相对内核布局的 M0 ZIP；解压后可直接启动客户端，也可执行归档中的 `clean-machine.ps1`。这是未签名的本地验证包，尚未完成正式分发许可清单。

## 干净机必须另验

准备无 Python/FFmpeg 的 Windows 10/11 x64 标准用户环境，仅复制 MediaDownloader 和 media-engine 产物目录。不要把开发 .venv 或系统工具加进 PATH。

1. 启动客户端，显式指定内核目录；完成窗口、字体和 DPI 检查。
2. 运行内核 `--self-test --output <新目录>`；要求三个捆绑工具均可用，中文视频/图集下载和解码通过。
3. 用实际平台样本完成下载、取消和关闭，检查无 worker/FFmpeg 残留。
4. 同一客户端使用 E1/E2 启动验证；E2 目前是相同代码的合成版本，仅证明独立选择边界。
5. 保存系统版本、工具清单、自检 JSON 和验收记录。删除开发机 PATH 只能作为本机独立性证据，不能代替此步骤。
