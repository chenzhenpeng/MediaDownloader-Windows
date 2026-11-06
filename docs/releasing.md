# 发布维护

## 命名与附件

| 类型 | 标签 | 标题 | 使用方式 |
| --- | --- | --- | --- |
| 应用 | `client-<版本>` | `Media Downloader <版本> · Windows x64` | 下载 Setup.exe |
| Worker | `worker-<版本>` | `[组件] Worker <版本>` | 应用自动安装 |
| Python | `python-runtime-<版本>` | `[组件] Python 环境 <版本>` | 应用自动安装 |
| 媒体工具 | `media-tools-<版本>` | `[组件] 媒体工具 <版本>` | 应用自动安装 |
| 当前目录 | `channel-components-v1` | `[更新渠道] 执行组件` | 应用自动读取 |

ParseHub 官方包直接来自 PyPI，不重新打包或改版本。Latest 只指向推荐应用安装包；当前仍为 Preview，标题和正文必须明确。组件和渠道均设置 `make_latest=false`。当前下载与更新入口不修改标签和附件名。

## 应用

1. 更新应用版本和 `CHANGELOG.md`，检查依赖锁和组件版本。
2. 在默认分支运行 `application-release.yml`，消费验签组件与官方 SDK，构建用户及 QA 安装包，创建草稿。
3. 独立 QA 目录验收安装、启动、修复、卸载、布局和组件更新；通过后公开。
4. 正文写清变化、安装方法、限制及数据兼容边界。附件只发布用户安装包与 `SHA256SUMS.txt`，不发布 QA 包、临时报告或缓存。
5. 核对附件摘要，再设为 Latest。

## 执行组件

`components-release.yml` 在 GitHub Actions 构建并检查完整组合，仅签名 `publish_components` 指定的变化组件并创建草稿。组件版本及签名 sequence 根据各自公开状态递增，不复用已发布标签替换二进制。

签名任务使用受保护的 `engine-release` 环境。仓库只保留公钥和信任配置；Fork 可构建测试，独立发布需要自己的密钥和客户端信任。

验收并公开组件后，运行 `component-catalog.yml`，传入目标标签和高于现有目录的 sequence；验证元数据后发布 `channel-components-v1/catalog.json` 与 `catalog.sig`。`component-catalog-renew.yml` 定期续签有效期，不重建组件。安装前验证整个候选组合，空闲切换，失败回滚。

`upstream-watch.yml` 只读监测 PyPI；官方 wheel 更新也须通过当前依赖和 Worker 的兼容检查。

## 历史渠道

仓库只保留当前解耦架构的应用、Worker、Python 环境、媒体工具和执行组件渠道 Release。旧的 `channel-stable`、`engine-*`、工具实验包与早期客户端 Release 已转为非公开草稿，其附件和更新入口不再公开提供；源码标签及 Git 历史保留追溯。旧客户端需重新安装当前版本。

后续维护须保留当前客户端引用的固定更新入口。迁移组件仓库应先更新客户端发现与信任配置，再安排旧渠道退役。

组件附件 `engine.zip`、`release.json`、`release.sig` 是下载协议的一部分，通过标签与元数据区分种类，不仅为页面美观重命名。
