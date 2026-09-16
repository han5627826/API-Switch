# 构建与发布工具

本目录是本工具的「构建流水线」。发布版由母版经**定制重打包**生成，发布新版本的操作如下：

```
母版 exe（作者本机保留，不入库）
   │  python repack.py --src <母版路径> --out ..\API Switch.exe --version 1.1.0
   ▼
发布版 API Switch.exe（替换品牌文案 + 注入功能后端 + 前端整体替换 + 写入版本号 + 换图标）
   │  python make_icon.py                  # 如需重新生成图标 new_icon.ico
   │  python publish.py --version 1.1.0    # 校验版本 → SHA-256 → 打 tag → 建 Release
   ▼
GitHub Release（tag + exe 附件） → 用户 exe 启动时自动检测并提示更新
```

- `repack.py` —— 对 PyInstaller 归档做外科手术：
  用 `feature_backend.build_make_server_code()` 整体替换后端 `server.make_server`
  （Qoder / Qoder CN / ZCode / TRAE Work CN / 一键更新 / 目标管理 路由一体），
  前端整体替换为 `../frontend` 三件套并按 `replacements.json` 应用文案补丁
  （HTML 锚点丢失即报错），更换本地数据目录名，替换图标，
  并修复原版「全新安装首次运行初始化不完整」的 bug。
  要求用与母版一致的 Python（3.12）运行。构建后自动跑自检（解包全部模块 + 关键路由存在）。
- `feature_backend.py` —— **功能后端唯一源码**。`FEATURE_SERVER_SRC` 是一段真实的
  Python 源码（替换母版 `make_server`），带行号可直接调试语义。
  桌面端（`E:\API-Modifier\_work\feature_pack.py`）与本发布版共用同一模板，保证行为一致。
  接口清单：`/api/targets`、`/api/qoder2/{list,import,delete}`、`/api/qodercn/{list,import,delete}`、
  `/api/zcode/{list,import,enable,delete}`、`/api/trae/{models,models/toggle,models/delete,prepare2}`、
  `/api/update/{check,start,status,apply}`。母版旧路由全部保持兼容。
- `../frontend/` —— 发布版前端源码（index.html / app.js / style.css）。
  `app.js` 里的 `__LIMITS_RAW__` 占位符在 repack 时用母版前端的 models.dev 快照填充；
  `replacements.json` 的 HTML 锚点必须在 index.html 中真实存在（构建时断言）。
- 单元测试：`python E:\API-Modifier\_work\test_backend.py`（把母版 server 字节码加载为真模块、
  替换 make_server、在临时 HOME 下起真 HTTP 服务逐接口验证；要求母版工具未运行，
  8765 端口占用会因新加的单实例保护而失败——这是预期行为）。
- `replacements.json` —— **文案映射表（母版中真实的旧名称 / URL / 端口等，已被
  `.gitignore` 排除，绝不提交）**。首次使用时参照 `replacements.sample.json` 创建。
- `make_icon.py` —— 生成 `new_icon.ico`（同目录存在时 repack 自动使用）。
- `publish.py` —— 一键发布：校验 exe 内置 `APP_VERSION` 与 tag 一致 → 计算 SHA-256 →
  `git tag` + `gh release create`。需要 [GitHub CLI](https://cli.github.com/)。

版本检查原理：exe 启动后请求 `api.github.com/repos/<UPDATE_REPO>/releases/latest`，
把返回的 `tag_name` 与内置 `APP_VERSION` 比对，仅当远程更新时提示。发布时务必保证
exe 内置版本号与 tag 一致（`publish.py` 会校验），老用户才能收到提示。

**历史教训（v1.0.0）**：旧 repack 用「只含更新路由」的 make_server 替换母版实现，
把母版已内置的 Qoder CN（qn_*）路由连带删掉，且无任何测试发现。
现在 make_server 的唯一出处是 `feature_backend.py`，且 `repack.py` 构建自检 +
`test_backend.py` 双保险。改功能只改 feature_backend.py，重新 repack / feature_pack 即可。
