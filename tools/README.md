# 构建与发布工具

本目录是本工具的「构建流水线」。发布版由母版经**定制重打包**生成，发布新版本的操作如下：

```
母版 exe（作者本机保留，不入库）
   │  python repack.py --src <母版路径> --out ..\API Switch.exe --version 1.1.0
   ▼
发布版 API Switch.exe（替换品牌文案 + 注入一键更新 + 写入版本号 + 换图标）
   │  python make_icon.py                  # 如需重新生成图标 new_icon.ico
   │  python publish.py --version 1.1.0    # 校验版本 → SHA-256 → 打 tag → 建 Release
   ▼
GitHub Release（tag + exe 附件） → 用户 exe 启动时自动检测并提示更新
```

- `repack.py` —— 对 PyInstaller 归档做外科手术：
  替换后端字节码与前端文案（品牌定制）、更换本地数据目录名、注入「一键更新」前后端模块、
  替换图标，并修复原版「全新安装首次运行初始化不完整」的 bug。
  补丁表为精确整串替换（HTML 锚点丢失即报错），要求用与母版一致的 Python（3.12）运行。
- `replacements.json` —— **文案映射表（母版中真实的旧名称 / URL / 端口等，已被
  `.gitignore` 排除，绝不提交）**。首次使用时参照 `replacements.sample.json` 创建。
- `make_icon.py` —— 生成 `new_icon.ico`（同目录存在时 repack 自动使用）。
- `publish.py` —— 一键发布：校验 exe 内置 `APP_VERSION` 与 tag 一致 → 计算 SHA-256 →
  `git tag` + `gh release create`。需要 [GitHub CLI](https://cli.github.com/)。

版本检查原理：exe 启动后请求 `api.github.com/repos/<UPDATE_REPO>/releases/latest`，
把返回的 `tag_name` 与内置 `APP_VERSION` 比对，仅当远程更新时提示。发布时务必保证
exe 内置版本号与 tag 一致（`publish.py` 会校验），老用户才能收到提示。
