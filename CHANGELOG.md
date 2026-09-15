# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2026-09-15

### 新增
- 首个公开发布版本：Codex / Qoder / Trae / Qoder CN 四个页签的一键配置与切换能力。
- 内置「一键更新」：启动时静默比对 GitHub Releases 最新版本，发现新版时右上角提示；确认后自动下载、SHA-256 校验、覆盖安装并自动重启。
- 全新安装修复：首次运行（无任何配置文件）时供应商库初始化不完整导致界面加载失败的问题。

### 变更
- 数据目录独立为 `%APPDATA%\APISwitch`，与任何早期版本互不干扰。
