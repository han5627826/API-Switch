#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
feature_pack.py —— 桌面版「API修改器」更新打包：对现有 exe 做外科手术式升级。

与 tools/repack.py 共用 feature_backend.FEATURE_SERVER_SRC（功能后端唯一源码）。
区别于 repack（发布版品牌定制）：
  - 不改品牌文案（桌面版品牌就是「API 修改器」，replacements 补丁不适用）
  - 不注入前端更新模块（APP_VERSION='desktop'，UPDATE_ENABLED=False）
  - 前端三件套用仓库 ../frontend 原样（HTML_REPL 是发布版品牌替换，不应用），
    仅注入「发现新版本」按钮占位（隐藏，不启用时不显示）——不需要，跳过。
用法：
  python feature_pack.py --src <桌面版exe> --out <桌面版exe> [--limits <limits快照.txt>]
要求：与母版一致的 Python（3.12）运行（marshal 跨版本不兼容）。
"""
import argparse, marshal, os, re, struct, sys, types, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import feature_backend  # noqa: E402

COOKIE_MAGIC = b'MEI\014\013\012\013\016'
FRONT_DIR = os.path.join(os.path.dirname(HERE), "frontend")


def read_archive(data):
    idx = data.rfind(COOKIE_MAGIC)
    _, pkgLen, tocOff, tocLen, pyvers, pylib = struct.unpack("!8sIIii64s", data[idx:idx + 88])
    archStart = len(data) - pkgLen
    toc = data[archStart + tocOff: archStart + tocOff + tocLen]
    entries, p = [], 0
    while p < len(toc):
        (esize,) = struct.unpack("!i", toc[p:p + 4])
        pos, csize, usize, flag, typ = struct.unpack("!IIIBc", toc[p + 4:p + 18])
        name = toc[p + 18:p + esize].rstrip(b"\0").decode()
        entries.append(dict(name=name, pos=pos, csize=csize, usize=usize, flag=flag, typ=typ))
        p += esize
    return archStart, pyvers, pylib, entries


def build_replacement_function(fn_code, old_code):
    return fn_code.replace(co_filename=old_code.co_filename, co_firstlineno=old_code.co_firstlineno,
                           co_name=old_code.co_name, co_qualname=old_code.co_qualname)


def _compile_src(src, name):
    mod = compile(src, "<feature_pack>", "exec")
    return next(k for k in mod.co_consts if isinstance(k, types.CodeType) and k.co_name == name)


NEW_ENSURE_BUILTIN_SRC = '''
def ensure_builtin(data):
    data.setdefault("qoder", {"imports": []})
    data.setdefault("trae", {"imports": []})
    data.setdefault("settings", {})
    data.setdefault("codex", {})
    providers = data["codex"].setdefault("providers", [])
    if not any(p.get("id") == "original" for p in providers):
        providers.insert(0, dict(BUILTIN_ORIGINAL))
    return data
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="桌面版 exe 路径（就地更新请与 --out 相同前先备份）")
    ap.add_argument("--out", required=True, help="输出 exe 路径")
    ap.add_argument("--limits", default="", help="LIMITS_RAW 快照文本文件（缺省沿用母版现有快照）")
    a = ap.parse_args()

    data = open(a.src, "rb").read()
    archStart, pyvers, pylib, entries = read_archive(data)

    def rd(e):
        b = data[archStart + e["pos"]: archStart + e["pos"] + e["csize"]]
        return zlib.decompress(b) if e["flag"] else b

    # 1) server 模块：ensure_builtin 修复 + make_server 全量替换（含卸载修复）
    pyz_e = next(e for e in entries if e["name"] == "PYZ.pyz")
    pyz_bytes = rd(pyz_e)
    t_off = struct.unpack('!i', pyz_bytes[8:12])[0]
    pyz_toc = marshal.loads(pyz_bytes[t_off:])
    typ_s, off_s, len_s = dict(pyz_toc)["server"]
    server_code = marshal.loads(zlib.decompress(pyz_bytes[off_s:off_s + len_s]))
    old_fn = next(k for k in server_code.co_consts if isinstance(k, types.CodeType) and k.co_name == "ensure_builtin")
    new_fn = build_replacement_function(_compile_src(NEW_ENSURE_BUILTIN_SRC, "ensure_builtin"), old_fn)
    server_code = server_code.replace(co_consts=tuple(new_fn if k is old_fn else k for k in server_code.co_consts))
    ms_src = feature_backend.build_make_server_code(version="desktop", repo="", update_enabled=False,
                                                    brand="API 修改器")
    old_ms = next(k for k in server_code.co_consts if isinstance(k, types.CodeType) and k.co_name == "make_server")
    new_ms = build_replacement_function(ms_src, old_ms)
    server_code = server_code.replace(co_consts=tuple(new_ms if k is old_ms else k for k in server_code.co_consts))

    # 2) 重建 PYZ
    body = b''; new_toc = []
    for name, (typ, off, length) in pyz_toc:
        blob = zlib.compress(marshal.dumps(server_code), 9) if name == "server" else pyz_bytes[off:off + length]
        new_toc.append((name, (typ, 12 + len(body), len(blob)))); body += blob
    toc_bytes = marshal.dumps(new_toc)
    new_pyz = b'PYZ\x00' + pyz_bytes[4:8] + struct.pack('!i', 12 + len(body)) + body + toc_bytes

    # 3) 前端三件套：仓库原样；app.js 填 LIMITS_RAW（--limits 或沿用母版现有快照）
    old_js = None
    for e in entries:
        if e["name"].replace("\\", "/").lower() == "static/app.js":
            old_js = rd(e).decode("utf-8")
    assert old_js, "static/app.js 未找到"
    m = re.search(r'const LIMITS_RAW = ".*?";', old_js, re.S)
    assert m, "现有 app.js 中未找到 LIMITS_RAW"
    limits_line = m.group(0)[len('const LIMITS_RAW = '):]
    if a.limits:
        limits_line = '"%s"' % open(a.limits, encoding="utf-8").read().strip().strip('"')
    new_blobs = {}
    for e in entries:
        n = e["name"].replace("\\", "/").lower()
        if n == "static/index.html":
            new_blobs[e["name"]] = open(os.path.join(FRONT_DIR, "index.html"), encoding="utf-8").read().encode("utf-8")
        elif n == "static/app.js":
            js = open(os.path.join(FRONT_DIR, "app.js"), encoding="utf-8").read()
            js = js.replace('"__LIMITS_RAW__";', limits_line)
            new_blobs[e["name"]] = js.encode("utf-8")
        elif n == "static/style.css":
            new_blobs[e["name"]] = open(os.path.join(FRONT_DIR, "style.css"), "rb").read()

    # 4) 重建 CArchive
    out_body = bytearray(data[:archStart]); newtoc = bytearray(); off = 0
    for e in entries:
        if e["name"] == "PYZ.pyz":
            blob = new_pyz; usize = len(new_pyz); flag = 0
        elif e["name"] in new_blobs:
            raw = new_blobs[e["name"]]; blob = zlib.compress(raw, 9); usize = len(raw); flag = 1
        else:
            blob = data[archStart + e["pos"]: archStart + e["pos"] + e["csize"]]; usize = e["usize"]; flag = e["flag"]
        name_b = e["name"].encode() + b"\0"
        newtoc += struct.pack("!iIIIBc", 18 + len(name_b), off, len(blob), usize, flag, e["typ"]) + name_b
        out_body += blob; off += len(blob)
    cookie = struct.pack("!8sIIii64s", COOKIE_MAGIC, off + len(newtoc) + 88, off, len(newtoc), pyvers, pylib)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "wb") as f:
        f.write(bytes(out_body) + bytes(newtoc) + cookie)
    print("written:", a.out, os.path.getsize(a.out), "bytes")

    # 5) 自检
    from PyInstaller.archive.readers import CArchiveReader
    cr = CArchiveReader(a.out)
    pyz = cr.open_embedded_archive('PYZ.pyz')
    sc2 = pyz.extract('server')
    ms = next(k for k in sc2.co_consts if isinstance(k, types.CodeType) and k.co_name == "make_server")
    kids = {k.co_name for k in ms.co_consts if isinstance(k, types.CodeType)}
    need = ['qn_import', 'q2_import', 'zc_import', 'tw_prepare', '_api_get', '_api_post', '_uninstall_cleanup']
    missing = [x for x in need if x not in kids]
    js2 = cr.extract("static" + chr(92) + "app.js").decode("utf-8")
    assert not missing and '/api/uninstall' in js2 and '__LIMITS_RAW__' not in js2, (missing,)
    html2 = cr.extract("static" + chr(92) + "index.html").decode("utf-8")
    i_chk, i_un, i_net = html2.index('btn-check-update'), html2.index('btn-uninstall'), html2.index('id="net-mask"')
    assert i_chk < i_un < i_net, "前端按钮布局自检失败"
    print("self-check: backend routes OK | uninstall(legacy cleanup) OK | frontend OK")


if __name__ == "__main__":
    main()
