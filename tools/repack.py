#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
repack.py —— 对母版 exe（PyInstaller 打包）做「外科手术式」定制重打包：
  1. 替换后端 server 模块的 make_server：feature_backend 统一模板
     （恢复母版 Qoder CN 路由 + 新增 Qoder 桌面版 / ZCode / TRAE Work CN + 一键更新后端）；
  2. 前端整体替换为 ../frontend 三件套（新页签 + 导入栏 + 目标管理），
     应用 replacements.json 的 HTML 锚点补丁与 JS 补丁（品牌 / 版本号 / LIMITS_RAW 快照）；
  3. 改写后端字节码其余字符串常量与 app 模块（品牌定制、数据目录改名）；
  4. 修复原版「全新安装首次运行 load_data 返回结构不完整」的初始化 bug（替换 ensure_builtin）；
  5. 替换应用图标（若存在 new_icon.ico）。

所有母版中真实存在的名称/URL/端口字符串保存在同目录 replacements.json
（已被 .gitignore 排除，绝不入库）。脚本仅包含通用机制。

用法：
  python repack.py --src "C:/path/母版.exe" --out "API Switch.exe" --version 1.1.0
要求：与母版一致的 Python（3.12）运行本脚本（marshal 跨版本不兼容）。
"""
import argparse, json, marshal, os, re, struct, sys, types, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
FRONT_DIR = os.path.join(os.path.dirname(HERE), "frontend")
sys.path.insert(0, HERE)
import feature_backend  # noqa: E402

COOKIE_MAGIC = b'MEI\014\013\012\013\016'

# 前端 app.js 文本补丁：品牌占位、版本号、LIMITS_RAW 快照来源（母版当前前端里提取）
def apply_js_repl(js, version, brand, master_js):
    m = re.search(r'const LIMITS_RAW = ".*?";', master_js, re.S)
    assert m, "master app.js 中未找到 LIMITS_RAW"
    js = js.replace('"__LIMITS_RAW__";', m.group(0)[len('const LIMITS_RAW = '):])
    js = js.replace('/* 前端逻辑 —— 所有目标页共用供应商库 */',
                    '/* %s 前端逻辑 —— 所有目标页共用供应商库 */' % brand)
    # 注入：云端一键更新模块（依赖 api()/toast()/confirmDlg()，追加在文件末尾安全）
    js = js + JS_UPDATE_TEMPLATE.replace("__VERSION__", version)
    return js


JS_UPDATE_TEMPLATE = r'''

/* ---------------- 云端一键更新（后端代理下载 + 覆盖安装） ---------------- */
const APP_VERSION = "__VERSION__";
let _updTimer = null;
async function updCheck(silent) {
  try {
    const j = await api("/api/update/check");
    if (!j.ok) { if (!silent) toast(j.error || "检查更新失败", true); return null; }
    const b = document.querySelector("#btn-update");
    if (j.has_update) {
      if (b) {
        b.classList.remove("hidden");
        b.textContent = "发现新版本 " + j.latest;
        b.title = "点击自动下载并安装更新（完成后自动重启）";
        b.disabled = false;
        b.onclick = updStart;
      }
      toast("发现新版本 " + j.latest + "，点右上角按钮一键更新", true);
    } else if (!silent) {
      toast("已是最新版本 v" + APP_VERSION);
    }
    return j;
  } catch (e) { if (!silent) toast("检查更新失败（网络或限流）", true); return null; }
}
async function updStart() {
  const b = document.querySelector("#btn-update");
  const info = await updCheck(false);
  if (!info || !info.has_update) return;
  const mb = (info.size / 1048576).toFixed(1);
  const msg = "发现新版本 " + info.latest + "（约 " + mb + " MB）。" +
    "将自动下载，完成后程序会短暂关闭并自动重启为新版本，是否继续？";
  if (!(await confirmDlg(msg))) return;
  const r = await api("/api/update/start", {});
  if (!r.ok) { toast(r.error || "启动下载失败", true); return; }
  if (b) { b.disabled = true; b.textContent = "下载中 0%"; }
  _updTimer = setInterval(updPoll, 500);
}
async function updPoll() {
  try {
    const s = await api("/api/update/status");
    const b = document.querySelector("#btn-update");
    if (s.stage === "downloading") {
      const pct = s.total ? Math.min(99, Math.floor(s.got * 100 / s.total)) : 0;
      if (b) b.textContent = "下载中 " + pct + "%";
    } else if (s.stage === "downloaded") {
      clearInterval(_updTimer);
      if (b) {
        b.textContent = "立即重启安装";
        b.disabled = false;
        b.onclick = async () => {
          b.disabled = true;
          try { await api("/api/update/apply", {}); } catch (e) {}
          document.body.innerHTML = '<div style="font:14px/1.8 sans-serif;padding:48px;color:#334">' +
            '正在重启到新版本…<br>窗口即将自动关闭，并在新版本启动后自动重新打开。</div>';
        };
      }
      toast("下载完成（已通过 SHA-256 校验），点「立即重启安装」完成升级");
    } else if (s.stage === "error") {
      clearInterval(_updTimer);
      if (b) { b.disabled = false; b.textContent = "重试更新"; }
      toast("更新失败：" + (s.detail || "未知错误") + "，可到发布页手动下载", true);
    }
  } catch (e) {}
}
{
  const hdr = document.querySelector(".header-actions");
  if (hdr && !document.querySelector("#btn-update")) {
    const b = document.createElement("button");
    b.id = "btn-update"; b.className = "btn ghost hidden";
    // 发现新版本按钮插到「检查更新」之后（若手动按钮存在），否则放行首
    const anchor = document.querySelector("#btn-check-update");
    if (anchor && anchor.nextSibling) hdr.insertBefore(b, anchor.nextSibling);
    else hdr.insertBefore(b, hdr.firstChild);
  }
  setTimeout(() => updCheck(true), 1500);
}
/* 手动检查更新：点击「检查更新」按钮立即发起检查并给出结果反馈 */
{
  const cb = document.querySelector("#btn-check-update");
  if (cb) cb.onclick = async () => {
    const old = cb.textContent;
    cb.disabled = true; cb.textContent = "检查中…";
    try {
      const j = await updCheck(false);
      if (j && j.has_update && cb) {
        // 有新版本时按钮短暂提示结果，随后恢复（一键更新按钮已单独显示）
        cb.textContent = "有新版本";
        setTimeout(() => { cb.textContent = old; cb.disabled = false; }, 2500);
        return;
      }
    } finally {
      if (!document.querySelector("#btn-update:not(.hidden)")) {
        cb.textContent = old; cb.disabled = false;
      }
    }
  };
}
'''

# 修复「全新安装 load_data 空库返回结构不完整」bug 的替换函数（与母版字节码同逻辑 + 补齐顶层键）。
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


def load_replacements():
    path = os.path.join(HERE, "replacements.json")
    if not os.path.exists(path):
        sys.exit("缺少 tools/replacements.json（参考 replacements.sample.json 创建；含母版真实字符串，勿提交）")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def patch_consts(code, table):
    changed = 0
    consts = []
    for k in code.co_consts:
        if isinstance(k, types.CodeType):
            nk, c = patch_consts(k, table); consts.append(nk); changed += c
        elif isinstance(k, str) and k in table:
            consts.append(table[k]); changed += 1
        elif isinstance(k, tuple):
            nt = tuple(table.get(x, x) if isinstance(x, str) else x for x in k)
            consts.append(nt)
            if nt != k: changed += 1
        else:
            consts.append(k)
    if not changed:
        return code, 0
    return code.replace(co_consts=tuple(consts)), changed


def build_replacement_function(fn_code, old_code):
    return fn_code.replace(co_filename=old_code.co_filename, co_firstlineno=old_code.co_firstlineno,
                           co_name=old_code.co_name, co_qualname=old_code.co_qualname)


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="母版 exe 路径（只读，绝不修改）")
    ap.add_argument("--out", required=True, help="输出 exe 路径")
    ap.add_argument("--version", default="1.0.0", help="写入前端 APP_VERSION 的版本号")
    a = ap.parse_args()

    R = load_replacements()
    server_str = R["SERVER_STR"]
    brand = R.get("BRAND", "API Switch")

    data = open(a.src, "rb").read()
    archStart, pyvers, pylib, entries = read_archive(data)

    def rd(e):
        b = data[archStart + e["pos"]: archStart + e["pos"] + e["csize"]]
        return zlib.decompress(b) if e["flag"] else b

    # 1) 后端 app 模块（CArchive typecode 's'）
    app_entry = next(e for e in entries if e["name"] == "app")
    app_code, ac = patch_consts(marshal.loads(rd(app_entry)), R["APP_STR"])
    print("app patches:", ac)

    # 2) 后端 server 模块（PYZ 内）：字符串补丁 + ensure_builtin 修复 + make_server 全量替换
    update_repo = R.get("UPDATE_REPO", "")
    assert update_repo, "replacements.json 需含 UPDATE_REPO（GitHub 用户名/仓库）"
    pyz_e = next(e for e in entries if e["name"] == "PYZ.pyz")
    pyz_bytes = rd(pyz_e)
    t_off = struct.unpack('!i', pyz_bytes[8:12])[0]
    pyz_toc = marshal.loads(pyz_bytes[t_off:])
    typ_s, off_s, len_s = dict(pyz_toc)["server"]
    server_code, sc = patch_consts(marshal.loads(zlib.decompress(pyz_bytes[off_s:off_s + len_s])), server_str)
    old_fn = next(k for k in server_code.co_consts if isinstance(k, types.CodeType) and k.co_name == "ensure_builtin")
    new_fn = build_replacement_function(
        _compile_src(NEW_ENSURE_BUILTIN_SRC, "ensure_builtin"), old_fn)
    server_code = server_code.replace(co_consts=tuple(new_fn if k is old_fn else k for k in server_code.co_consts))
    ms_src = feature_backend.build_make_server_code(
        version=a.version, repo=update_repo, update_enabled=True, brand=brand)
    old_ms = next(k for k in server_code.co_consts if isinstance(k, types.CodeType) and k.co_name == "make_server")
    new_ms = build_replacement_function(ms_src, old_ms)
    server_code = server_code.replace(co_consts=tuple(new_ms if k is old_ms else k for k in server_code.co_consts))
    print("server patches:", sc)
    assert ac >= 1 and sc >= 1, "sanity: 至少应有补丁命中；检查 replacements.json 是否完整"

    # 3) 重建 PYZ（条目偏移以 PYZ 头后第 0 字节起算，需加 12 字节头偏移）
    body = b''; new_toc = []
    for name, (typ, off, length) in pyz_toc:
        blob = zlib.compress(marshal.dumps(server_code), 9) if name == "server" else pyz_bytes[off:off + length]
        new_toc.append((name, (typ, 12 + len(body), len(blob)))); body += blob
    toc_bytes = marshal.dumps(new_toc)
    new_pyz = b'PYZ\x00' + pyz_bytes[4:8] + struct.pack('!i', 12 + len(body)) + body + toc_bytes

    # 4) 前端：仓库三件套 + 补丁（HTML 锚点校验、JS 品牌/版本/LIMITS_RAW、更新模块注入、更新按钮）
    old_js = None
    for e in entries:
        if e["name"].replace("\\", "/").lower() == "static/app.js":
            old_js = rd(e).decode("utf-8")
    assert old_js, "母版 static/app.js 未找到"
    new_blobs = {}
    for e in entries:
        n = e["name"].replace("\\", "/").lower()
        if n == "static/index.html":
            html = open(os.path.join(FRONT_DIR, "index.html"), encoding="utf-8").read()
            for old, new in R["HTML_REPL"]:
                assert old in html, "HTML anchor missing: %r" % old[:40]
                html = html.replace(old, new)
            html = html.replace(
                '    <button id="btn-check-update" class="btn ghost" title="手动检查是否为最新版本">检查更新</button>',
                '    <button id="btn-check-update" class="btn ghost" title="手动检查是否为最新版本">检查更新</button>\n    <button id="btn-update" class="btn ghost hidden" title="发现新版本时点击一键更新">发现新版本</button>')
            # 手动「检查更新」按钮：置于网络设置右侧（同一行）
            assert 'id="btn-check-update"' in html, "index.html 缺少 btn-check-update 按钮（检查更新）"
            assert html.index('id="btn-net"') < html.index('id="btn-check-update"'), \
                "btn-check-update 必须位于 btn-net（网络设置）之后"
            new_blobs[e["name"]] = html.encode("utf-8")
        elif n == "static/app.js":
            js = open(os.path.join(FRONT_DIR, "app.js"), encoding="utf-8").read()
            js = apply_js_repl(js, a.version, brand, old_js)
            new_blobs[e["name"]] = js.encode("utf-8")
        elif n == "static/style.css":
            new_blobs[e["name"]] = open(os.path.join(FRONT_DIR, "style.css"), "rb").read()
        elif n == "app.ico":
            ico = os.path.join(HERE, "new_icon.ico")
            if os.path.exists(ico):
                new_blobs[e["name"]] = open(ico, "rb").read()

    # 5) 重建 CArchive（PYZ 必须以未压缩 flag=0 存入，供运行时嵌套寻址）
    out_body = bytearray(data[:archStart]); newtoc = bytearray(); off = 0
    for e in entries:
        if e["name"] == "app":
            raw = marshal.dumps(app_code); blob = zlib.compress(raw, 9); usize = len(raw); flag = 1
        elif e["name"] == "PYZ.pyz":
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
    print("written:", a.out, os.path.getsize(a.out), "bytes, version", a.version)

    # 6) 自检：重读输出、全模块解压、关键路由存在
    from PyInstaller.archive.readers import CArchiveReader
    cr = CArchiveReader(a.out)
    pyz = cr.open_embedded_archive('PYZ.pyz')
    ok = 0
    for name in pyz.toc:
        pyz.extract(name); ok += 1
    sc2 = pyz.extract('server')
    ms = next(k for k in sc2.co_consts if isinstance(k, types.CodeType) and k.co_name == "make_server")
    kids = {k.co_name for k in ms.co_consts if isinstance(k, types.CodeType)}
    need = ['qn_import', 'q2_import', 'zc_import', 'zc_set_enabled', 'tw_prepare', '_api_get', '_api_post']
    missing = [n for n in need if n not in kids]
    js = cr.extract("static\\app.js").decode("utf-8")
    assert "/api/zcode/import" in js and APP_VERSION_OK(js, a.version) and not missing, \
        (missing, "version" if not APP_VERSION_OK(js, a.version) else "")
    html2 = cr.extract("static\\index.html").decode("utf-8")
    assert 'id="btn-check-update"' in html2 and html2.index('id="btn-net"') < html2.index('id="btn-check-update"') \
        and html2.index('id="btn-check-update"') < html2.index('id="btn-update"'), "前端按钮布局自检失败"
    # 「卸载并清除数据」按钮：位于顶栏「检查更新」右侧（不在网络设置弹窗内）
    assert html2.index('id="btn-check-update"') < html2.index('id="btn-uninstall"') < html2.index('id="net-mask"'), \
        "btn-uninstall 必须位于顶栏（检查更新之后、网络设置弹窗之前）"
    print("self-check: PYZ", ok, "modules | backend routes OK | APP_VERSION", a.version)


def _compile_src(src, name):
    mod = compile(src, "<repack>", "exec")
    return next(k for k in mod.co_consts if isinstance(k, types.CodeType) and k.co_name == name)


def APP_VERSION_OK(js, version):
    return ('const APP_VERSION = "%s";' % version) in js


if __name__ == "__main__":
    main()
