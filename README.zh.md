<p align="center">
  <img src="https://raw.githubusercontent.com/xiongqi123123/LeafLink/main/resource/leaflink.png" alt="LeafLink Logo" width="220" />
</p>

<h1 align="center">LeafLink</h1>

<p align="center">本地目录与 Overleaf / cn.overleaf 项目同步 CLI</p>

<p align="center">
  <a href="https://pypi.org/project/leaflink/"><img src="https://img.shields.io/pypi/v/leaflink?label=PyPI&cacheSeconds=300" alt="PyPI" /></a>
<a href="https://pypi.org/project/leaflink/"><img src="https://img.shields.io/pypi/pyversions/leaflink?cacheSeconds=300" alt="Python" /></a>
  <a href="https://github.com/xiongqi123123/LeafLink/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/xiongqi123123/LeafLink/ci.yml?branch=main&label=CI" alt="CI" /></a>
  <a href="https://github.com/xiongqi123123/LeafLink"><img src="https://img.shields.io/github/stars/xiongqi123123/LeafLink?style=flat" alt="GitHub stars" /></a>
  <a href="https://github.com/xiongqi123123/LeafLink/blob/main/LICENSE.txt"><img src="https://img.shields.io/github/license/xiongqi123123/LeafLink" alt="License" /></a>
</p>

<p align="center">
  <a href="./README.en.md">English</a> |
  <a href="https://github.com/xiongqi123123/LeafLink">GitHub</a> |
  <a href="https://pypi.org/project/leaflink/">PyPI</a>
</p>

<p align="center"><strong>浏览器登录、本地拉取、远端推送、PDF 下载、伪实时协作同步，一套命令完成。</strong></p>

## 项目简介

LeafLink 是一个开源命令行工具，用于在本地目录和 Overleaf 项目之间同步文件，不依赖 Overleaf 的付费 Git 集成。

它参考了 `overleaf-sync` 的产品形态与命令体验，但不是 fork，而是从零重写的现代化实现，目标是：

- 更清晰的工程分层
- 更稳定的浏览器登录与会话持久化
- 更可靠的本地/远端状态追踪
- 更适合扩展的同步引擎与测试结构

## 为什么重写，而不是 fork

- 希望从一开始就把认证、远端 client、同步引擎、CLI 解耦
- 需要优先支持 `overleaf.com` 和 `cn.overleaf.com`
- 需要新增 `sync` 命令来做“本地 watch + 远端轮询”的伪实时协作
- 需要更容易发布到 PyPI、接入 CI、编写单元测试和长期维护

## 功能概览

- 浏览器登录并持久化会话 Cookie
- 手动导入 Cookie 作为后备认证方案
- 列出账号下项目
- 通过项目 URL / 项目 ID / 项目名克隆项目
- 拉取远端变更到本地
- 推送本地变更到远端
- 下载最新编译 PDF
- 查看本地与远端差异
- `sync` 伪实时同步：本地监听 + 远端轮询 + 冲突处理
- 文本冲突使用 `merge3` 三方合并
- 二进制文件安全同步，不假设所有文件都是文本

## 支持的网址

- `https://www.overleaf.com/project/...`
- `https://cn.overleaf.com/project/...`

## 安装方式

### 通过 PyPI 安装

```bash
pip install leaflink
```

安装后可直接使用：

```bash
leaflink --help
```

### 安装可选依赖

```bash
pip install "leaflink[browser,watch]"
```

- `browser`：安装 Playwright，用于浏览器登录和部分远端发现能力
- `watch`：安装 `watchdog`，用于 `leaflink sync`

### 从源码安装

```bash
git clone https://github.com/xiongqi123123/LeafLink.git
cd LeafLink
pip install .
```

### 首次使用 Playwright

```bash
playwright install chromium
```

## 认证方式

LeafLink 不保存用户名或密码明文，只保存必要的会话信息。

默认配置目录：

- `~/.config/leaflink/auth.json`
- `~/.config/leaflink/config.toml`

### 浏览器登录

```bash
leaflink login
leaflink login --base-url https://cn.overleaf.com
```

示意输出：

```text
[auth] Complete login in the browser window. leaflink will detect the session automatically and close the browser.
[ok] Saved session for https://cn.overleaf.com
```

### 手动导入 Cookie

```bash
leaflink auth import --base-url https://www.overleaf.com --cookie-file cookies.json
```

示意输出：

```text
[ok] Imported cookies for https://www.overleaf.com
```

### 登出

```bash
leaflink logout
```

示意输出：

```text
[ok] Removed saved auth session.
```

## 快速开始

```bash
leaflink login --base-url https://cn.overleaf.com
leaflink list
leaflink clone "Sample Paper Draft"
cd sample-paper-draft
leaflink status
leaflink pull
leaflink push
leaflink download --output build/output.pdf
leaflink sync
```

## 命令与示例输出

以下所有项目名、项目 ID、路径和文件内容都只是演示示例。

### `leaflink list`

用于列出当前账号下可访问的 Overleaf 项目，适合在 clone 前先确认项目名称、项目 ID 和最近更新时间。

```bash
leaflink list
```

```text
Name                         Project ID                Updated
---------------------------  ------------------------  ------------------------
Sample Paper Draft          a1b2c3d4e5f60718293a4b5c  2026-03-27T09:16:42.180Z
Research Notes              b2c3d4e5f60718293a4b5c6d  2026-03-24T12:08:09.011Z
Resume Template CN          c3d4e5f60718293a4b5c6d7e  2026-03-21T07:45:33.501Z
```

### `leaflink clone`

用于将远端项目完整拉取到本地目录，同时初始化 `.leaflink/` 元数据，建立本地目录与远端项目的映射关系。

```bash
leaflink clone a1b2c3d4e5f60718293a4b5c
leaflink clone "Sample Paper Draft"
leaflink clone https://www.overleaf.com/project/a1b2c3d4e5f60718293a4b5c ./paper-demo
```

```text
[ok] Cloned Sample Paper Draft into sample-paper-draft
```

### `leaflink status`

用于只做分析，不执行同步。它会检查本地和远端的新增、修改、删除以及潜在冲突，适合在 pull 或 push 之前先预览差异。

```bash
leaflink status
```

```text
[local] added: figures/overview.pdf
[local] modified: main.tex
[local] deleted: -
[remote] added: appendix.tex
[remote] modified: refs.bib
[remote] deleted: drafts/old-outline.tex
[conflicts] -
```

### `leaflink pull`

用于把远端项目中的最新变更同步到本地目录。它会处理新增、修改、删除，并在检测到重叠文本编辑时进入冲突处理流程。

```bash
leaflink pull
leaflink pull --conflict-strategy keep-remote
```

```text
[2026-03-27 14:06:11] [remote] changed: refs.bib (saved 2026-03-27 14:05:57, by collaborator)
[2026-03-27 14:06:11] [pull] updated: refs.bib (saved 2026-03-27 14:05:57, by collaborator)
[2026-03-27 14:06:11] [pull] added: appendix.tex
```

冲突示意：

```text
[2026-03-27 14:06:11] [conflict] main.tex
Local and remote edits overlap in the same text region.
...
<<<<<<< local/main.tex
\title{Sample Paper Draft v2}
||||||| base/main.tex
\title{Sample Paper Draft}
=======
\title{Sample Paper Draft Revised}
>>>>>>> remote/main.tex
Choose a resolution:
1. keep remote
2. keep local
3. duplicate both
```

### `leaflink push`

用于把本地目录中的变更上传到远端项目。它会尽量只上传发生变化的文件，并兼容常见二进制资源文件。

```bash
leaflink push
leaflink push --dry-run
```

```text
[2026-03-27 14:07:42] [push] uploaded: main.tex (saved 2026-03-27 14:07:38)
[2026-03-27 14:07:42] [push] uploaded: figures/overview.pdf (saved 2026-03-27 14:07:11)
```

### `leaflink download`

用于下载远端项目最近一次成功编译生成的 PDF，适合在本地归档、投递或集成到其他构建流程中。

```bash
leaflink download
leaflink download --output build/paper.pdf
```

```text
[ok] Downloaded PDF to /path/to/project/build/paper.pdf
```

### `leaflink sync`

用于启动“伪实时同步”模式。它会监听本地文件变化并自动 push，同时按固定间隔轮询远端变化并自动 pull，在协作写作场景下尤其有用。

```bash
leaflink sync
leaflink sync --interval 15 --debounce 2.0
leaflink sync --once
```

```text
[2026-03-27 13:21:23] [sync] Preparing sync service for Sample Paper Draft.
[2026-03-27 13:21:23] [sync] Project lock acquired for Sample Paper Draft.
[2026-03-27 13:21:23] [sync] Starting local watcher.
[2026-03-27 13:21:23] [sync] Sync service started. Watching /path/to/project (remote poll: 10.0s, debounce: 1.5s).
[2026-03-27 13:21:31] [local] modified: main.tex (saved 2026-03-27 13:21:30)
[2026-03-27 13:21:33] [push] uploaded: main.tex (saved 2026-03-27 13:21:30)
[2026-03-27 13:21:43] [sync] Checking remote changes.
[2026-03-27 13:21:44] [remote] changed: refs.bib (saved 2026-03-27 13:21:40, by collaborator)
[2026-03-27 13:21:44] [pull] updated: refs.bib (saved 2026-03-27 13:21:40, by collaborator)
```

## `.leafignore` 示例

```gitignore
# LeafLink metadata
.leaflink/

# Git
.git/

# macOS
.DS_Store

# LaTeX temporary files
*.aux
*.log
*.out
*.fls
*.fdb_latexmk
*.synctex.gz
*.synctex(busy)

# Custom rules
build/
dist/
```

完整示例见 [examples/leafignore.example](examples/leafignore.example)。

## 冲突处理说明

LeafLink 使用共同基线、本地版本、远端版本进行三方合并：

- 不同位置的文本修改会尽量自动合并
- 重叠修改会进入冲突流程
- 二进制文件不会尝试自动 merge

冲突时可选择：

1. `keep remote`：使用云端版本覆盖本地
2. `keep local`：使用本地版本覆盖云端
3. `duplicate both`：保留本地版本，并将远端版本写成冲突副本

## `sync` 的原理与限制

`leaflink sync` 是“伪实时同步”，不是严格意义上的实时多人协同编辑。

它的工作方式是：

- 使用 `watchdog` 监听本地目录变更
- 用 debounce 合并短时间内的多次本地写入
- 定期轮询远端项目变化
- 尽量自动 push / pull
- 遇到重叠编辑时进入冲突处理

限制说明：

- 远端变化不是通过服务端推送，而是通过轮询获取
- 文本文件更适合自动合并，二进制文件冲突需要人工选择策略
- 如果远端私有接口变更，个别写入链路可能需要随 Overleaf 前端更新而调整

## 本地元数据目录

每个已 clone 的项目都会在根目录生成：

```text
.leaflink/
  project.json
  state.json
  lock
  cache/
  logs/
```

LeafLink 的元数据不会散落在项目根目录其他位置。

## 安全说明

- 不保存用户名密码明文
- 只保存必要的会话 Cookie / session
- 日志输出默认不会打印敏感认证信息
- 建议仅在个人可信设备上保存会话

## Star 统计

[![Star History Chart](https://api.star-history.com/svg?repos=xiongqi123123/LeafLink&type=Date)](https://star-history.com/#xiongqi123123/LeafLink&Date)

## 开发与发布

- 安装开发依赖：`pip install -e ".[dev,browser,watch]"`
- 运行测试：`python -m unittest discover -s tests -v`
- 本地打包：`python scripts/build_dist.py`
- GitHub Actions：
  - CI: [`.github/workflows/ci.yml`](.github/workflows/ci.yml)
  - 发布: [`.github/workflows/publish.yml`](.github/workflows/publish.yml)

## 开源协议

本项目采用 [Apache License 2.0](LICENSE.txt)。
