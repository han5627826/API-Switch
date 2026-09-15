# API Switch

一个**纯本地、绿色免安装**的 Windows 桌面小工具：为 AI 编程工具（Codex / Qoder / Trae / Qoder CN）**一键配置与切换自定义模型供应商**（中转站 / 自建 API），省去手动改配置文件的麻烦。
<img width="1384" height="991" alt="image" src="https://github.com/user-attachments/assets/4b7a7218-93ac-478e-bf80-197549af0347" />



## 功能一览

| 页签 | 目标软件 | 作用 |
|------|----------|------|
| Codex | ChatGPT 桌面版 / Codex CLI | 添加 / 切换 API 供应商（写入 `~/.codex/config.toml` 托管区块） |
| Qoder | Qoder | 把供应商的模型批量导入 Qoder 自定义模型列表 |
| Trae | Trae / TRAE SOLO CN | 自动复制模型信息并启动 Trae（Trae 的 Key 为闭源加密，无法代写） |
| Qoder CN | Qoder CLI / Qoder CN | 写入 `~/.qoder-cn/settings.json` 的 BYOK 配置 |

核心特性：

- **供应商库统一管理**：一次录入，四个页签共用；自带不可删除的「原始配置」，随时还原官方登录。
- **Key 安全**：API Key 用 Windows DPAPI 加密保存，只在本机可解密；`config.toml` / `auth.json` 首次修改前自动备份。
- **模型识别**：内置 models.dev 规格表 + 在线更新，自动识别各模型的上下文 / 输出上限；支持「测试连接」「获取模型列表」。
- **本地服务仅绑定 127.0.0.1**，外部无法访问；程序本身不上传任何数据。
- **一键更新**：启动时静默比对 GitHub Releases，发现新版本时右上角出现提示按钮；点击后自动下载、SHA-256 校验、覆盖安装并重启，配置保留（这是唯一的联网检查，且只访问 GitHub API）。

## 下载与使用

1. 到 [Releases](../../releases) 下载最新版 `APISwitch-vX.Y.Z.exe`（下载后可随意重命名）；
2. 双击运行即可（无需安装、无需管理员权限；首次运行如被 Windows SmartScreen 拦截，选择「仍要运行」）；
3. 详细说明见 [docs/使用说明.md](docs/使用说明.md)。

## 更新机制

工具内置一键更新：打开后自动向 GitHub Releases API 查询最新版本号，发现更新时在右上角显示「发现新版本 vX.Y.Z」按钮；点击后自动下载新版本、SHA-256 校验、覆盖安装并重启，供应商配置全部保留。发布者只需打 tag、上传 exe 即可发布新版本，流程见 [tools/README.md](tools/README.md)。

## 许可

[MIT](LICENSE) © han5627826
