#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
publish.py —— 发布新版本：校验 exe 内置版本号 → 计算 SHA-256 → 打 git tag → 创建 GitHub Release。
前置：安装并登录 GitHub CLI（gh auth login）。

用法：
  python tools/publish.py --version 1.1.0 [--exe API Switch.exe] [--notes "更新说明"] [--dry-run]
"""
import argparse, hashlib, os, re, subprocess, sys

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="如 1.1.0")
    ap.add_argument("--exe", default=os.path.join(here, "API Switch.exe"))
    ap.add_argument("--notes", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", a.version):
        sys.exit("版本号需形如 1.1.0")
    if not os.path.exists(a.exe):
        sys.exit("找不到 exe: " + a.exe)

    # 防呆：确认 exe 里注入的 APP_VERSION 与要发布的 tag 一致，
    # 否则老用户收不到提示 / 新装用户会看到升级提示。
    from PyInstaller.archive.readers import CArchiveReader
    js = CArchiveReader(a.exe).extract("static\\app.js").decode("utf-8")
    m = re.search(r'APP_VERSION = "([^"]+)"', js)
    if not m:
        sys.exit("exe 内未找到 APP_VERSION，请用 tools/repack.py --version 重新打包")
    if m.group(1) != a.version:
        sys.exit(f"exe 内置版本 {m.group(1)} != 发布版本 {a.version}，请先用 repack.py 重新打包")

    digest = sha256(a.exe)
    tag = "v" + a.version
    # GitHub 上传接口会截断非 ASCII 文件名，附件统一用 ASCII 名
    asset_name = f"APISwitch-{tag}.exe"
    import shutil
    staged = os.path.join(os.path.dirname(os.path.abspath(a.exe)), asset_name)
    shutil.copyfile(a.exe, staged)
    notes = (a.notes or f"API Switch {tag}").strip() + f"\n\nSHA-256: {digest}\n下载后重命名为任意名称即可使用（建议 API Switch.exe）。"
    print("SHA-256:", digest)

    cmds = [
        ["git", "add", "-A"],
        ["git", "commit", "-m", f"release: {tag}"],
        ["git", "tag", tag],
        ["git", "push", "origin", "main", "--follow-tags"],
        ["gh", "release", "create", tag, staged, "--title", tag, "--notes", notes],
    ]
    for c in cmds:
        print("$", " ".join(f'"{x}"' if " " in x else x for x in c))
        if not a.dry_run:
            subprocess.run(c, check=True)

if __name__ == "__main__":
    main()
