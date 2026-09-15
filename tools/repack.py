#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
repack.py —— 对母版 exe（PyInstaller 打包）做「外科手术式」定制重打包：
  1. 改写后端字节码（CArchive 内 app 脚本 + PYZ 内 server 模块）中的字符串常量（品牌定制）；
  2. 改写前端 index.html / app.js 的标题、示例文案；
  3. 更换本地数据目录名（与母版隔离，首运行为空库）；
  4. 注入「检查更新」前端模块（拉取 GitHub Releases 最新版本比对，发现更新才提示）；
  5. 修复原版「全新安装首次运行 load_data 返回结构不完整」的初始化 bug（替换 ensure_builtin 函数）；
  6. 替换应用图标（若存在 new_icon.ico）。

所有母版中真实存在的名称/URL/端口字符串保存在同目录 replacements.json
（已被 .gitignore 排除，绝不入库）。脚本仅包含通用机制。

用法：
  python repack.py --src "C:/path/母版.exe" --out "API Switch.exe" --version 1.0.0
要求：与母版一致的 Python（3.12）运行本脚本（marshal 跨版本不兼容）。
"""
import argparse, json, marshal, os, struct, sys, types, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
COOKIE_MAGIC = b'MEI\014\013\012\013\016'

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
    hdr.insertBefore(b, hdr.firstChild);
  }
  setTimeout(() => updCheck(true), 1500);
}
'''

# 替换 server.make_server：保留原语义（返回 ThreadingHTTPServer 或端口占用时 None），
# 但把 Handler 包一层 UpdateHandler，增加 /api/update/* 路由（检查/下载/校验/覆盖重启）。
# 用到的模块级全局（json/os/re/sys/time/threading/subprocess/urllib/DATA_DIR/Handler/
# ThreadingHTTPServer/get_proxy/CREATE_NO_WINDOW）均为母版 server 模块已有名字。
PY_UPDATE_TEMPLATE = r'''
def make_server():
    import hashlib

    APP_VERSION = "__VERSION__"
    UPDATE_REPO = "__REPO__"

    UPD = {"stage": "idle", "detail": "", "got": 0, "total": 0,
           "latest": "", "url": "", "asset": "", "asset_url": "", "digest": ""}
    UPD_LOCK = threading.Lock()

    def _proxy_opener():
        try:
            px = get_proxy()
        except Exception:
            px = None
        if px:
            return urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": px, "https": px}))
        return urllib.request.build_opener()

    def _ver_tuple(s):
        s = re.sub(r"^[vV]", "", str(s or "").strip())
        out = []
        for part in s.split("."):
            m = re.match(r"\d+", part)
            out.append(int(m.group()) if m else 0)
        while len(out) < 3:
            out.append(0)
        return tuple(out[:3])

    def _upd_check():
        headers = {"Accept": "application/vnd.github+json",
                   "User-Agent": "APISwitch-updater"}
        # 可选：设置环境变量 GITHUB_TOKEN 可绕过匿名限流（仅开发者调试用，不影响普通用户）
        tok = os.environ.get("GITHUB_TOKEN") or ""
        if tok:
            headers["Authorization"] = "Bearer " + tok
        req = urllib.request.Request(
            "https://api.github.com/repos/" + UPDATE_REPO + "/releases/latest",
            headers=headers)
        with _proxy_opener().open(req, timeout=15) as r:
            j = json.loads(r.read().decode("utf-8"))
        tag = j.get("tag_name") or ""
        has = _ver_tuple(APP_VERSION) < _ver_tuple(tag)
        asset_url, name, size, digest = "", "", 0, ""
        for a in j.get("assets") or []:
            an = a.get("name") or ""
            if an.lower().endswith(".exe"):
                asset_url = a.get("browser_download_url") or ""
                name, size = an, a.get("size") or 0
                digest = a.get("digest") or ""
                break
        has = bool(has and asset_url)
        with UPD_LOCK:
            UPD.update(latest=tag, url=j.get("html_url") or "", asset=name,
                       asset_url=asset_url, digest=digest)
            UPD["got"] = 0
            UPD["total"] = size
        return {"ok": True, "current": APP_VERSION, "latest": tag,
                "has_update": has, "url": j.get("html_url") or "",
                "asset": name, "size": size}

    def _upd_download():
        with UPD_LOCK:
            if UPD["stage"] == "downloading":
                return
            UPD.update(stage="downloading", got=0, detail="")
            url, digest = UPD["asset_url"], UPD["digest"]
        dest = os.path.join(DATA_DIR, "update.pending.exe")
        part = dest + ".part"
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            req = urllib.request.Request(url, headers={"User-Agent": "APISwitch-updater"})
            h = hashlib.sha256()
            got = 0
            with _proxy_opener().open(req, timeout=60) as r, open(part, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                with UPD_LOCK:
                    if total:
                        UPD["total"] = total
                while True:
                    chunk = r.read(262144)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    with UPD_LOCK:
                        UPD["got"] = got
            if digest:
                want = digest.split(":", 1)[-1]
                if h.hexdigest().lower() != want.lower():
                    raise ValueError("SHA-256 校验失败，已放弃安装")
            os.replace(part, dest)
            with UPD_LOCK:
                UPD.update(stage="downloaded", got=got)
        except Exception as e:
            try:
                os.remove(part)
            except OSError:
                pass
            with UPD_LOCK:
                UPD.update(stage="error", detail=str(e)[:200])

    def _upd_apply():
        old = sys.executable
        new = os.path.join(DATA_DIR, "update.pending.exe")
        if not os.path.exists(new):
            return {"ok": False, "error": "尚未下载新版本"}
        pid = os.getpid()
        pid = os.getpid()
        bat = os.path.join(DATA_DIR, "update_apply.bat")
        # 关键点：
        # 1) PyInstaller onefile 的父(bootloader)进程退出前，exe 一直被锁；且父进程退出时
        #    会删除自己的 _MEI 临时目录。若在删除完成前启动新实例，新实例（继承 _MEIPASS2
        #    指向旧目录）会失败。因此：move 成功 == 父进程已完全退出 == 临时目录已清理。
        # 2) 批处理由 Python 派生，环境里带着 _MEIPASS2，启动新实例前必须清空。
        # 3) 不按 PID 等待（父进程 PID 与子进程不同），直接重试 move，最长约 60 秒。
        script = (
            "@echo off\r\n"
            'set "_PYI_ARCHIVE_FILE="\r\n'
            'set "_PYI_APPLICATION_HOME_DIR="\r\n'
            'set "_MEIPASS2="\r\n'
            'set "MEIPASS2="\r\n'
            "set /a t=0\r\n"
            ":loop\r\n"
            "ping -n 2 127.0.0.1 >nul\r\n"
            'move /y "%s" "%s" >nul 2>&1\r\n'
            "if not errorlevel 1 goto ready\r\n"
            "set /a t+=1\r\n"
            "if %%t%% lss 60 goto loop\r\n"
            "goto cleanup\r\n"
            ":ready\r\n"
            "ping -n 3 127.0.0.1 >nul\r\n"
            'start "" "%s"\r\n'
            ":cleanup\r\n"
            'del "%%~f0" >nul 2>&1\r\n'
        ) % (new, old, old)
        try:
            with open(bat, "w", encoding="mbcs") as f:
                f.write(script)
            # 关键：剔除引导器传给子进程的内部变量（PyInstaller 6.x 为 _PYI_*，旧版为 _MEIPASS2）。
            # 否则 cmd 及 start 出的新 exe 会继承「归档/临时目录」指针，去加载旧进程
            # 已删除的 _MEI 目录而报「Failed to load Python DLL」。
            clean_env = {k: v for k, v in os.environ.items()
                         if not k.upper().startswith(("_PYI_", "MEIPASS", "_MEIPASS"))}
            subprocess.Popen(["cmd", "/c", bat], env=clean_env,
                             creationflags=CREATE_NO_WINDOW, close_fds=True)
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

        def _die():
            time.sleep(0.6)
            os._exit(0)
        threading.Thread(target=_die, daemon=True).start()
        return {"ok": True}

    class UpdateHandler(Handler):
        def do_GET(self):
            if not self._host_allowed():
                self._send(403, {"error": "forbidden"})
                return
            p = self.path.split("?", 1)[0]
            if p == "/api/update/check":
                try:
                    self._send(200, _upd_check())
                except Exception as e:
                    self._send(200, {"ok": False, "error": str(e)[:200]})
                return
            if p == "/api/update/status":
                with UPD_LOCK:
                    self._send(200, dict(UPD))
                return
            return Handler.do_GET(self)

        def do_POST(self):
            if not self._host_allowed():
                self._send(403, {"error": "forbidden"})
                return
            p = self.path.split("?", 1)[0]
            if p == "/api/update/start":
                threading.Thread(target=_upd_download, daemon=True).start()
                self._send(200, {"ok": True})
                return
            if p == "/api/update/apply":
                self._send(200, _upd_apply())
                return
            return Handler.do_POST(self)

    try:
        return ThreadingHTTPServer(("127.0.0.1", 8765), UpdateHandler)
    except OSError:
        return None
'''

# 修复「全新安装 load_data 空库返回结构不完整」bug 的替换函数（与母版字节码同逻辑 + 补齐顶层键）。
# BUILTIN_ORIGINAL / 内置供应商 id 是母版既有全局名，替换后继续可用。
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


def build_replacement_function(src, target_name, old_code):
    mod = compile(src, "<repack>", "exec")
    fn = next(k for k in mod.co_consts if isinstance(k, types.CodeType) and k.co_name == target_name)
    return fn.replace(co_filename=old_code.co_filename, co_firstlineno=old_code.co_firstlineno,
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

    data = open(a.src, "rb").read()
    archStart, pyvers, pylib, entries = read_archive(data)

    def rd(e):
        b = data[archStart + e["pos"]: archStart + e["pos"] + e["csize"]]
        return zlib.decompress(b) if e["flag"] else b

    # 1) 后端 app 模块（CArchive typecode 's'）
    app_entry = next(e for e in entries if e["name"] == "app")
    app_code, ac = patch_consts(marshal.loads(rd(app_entry)), R["APP_STR"])
    print("app patches:", ac)

    # 2) 后端 server 模块（PYZ 内），含 ensure_builtin 逻辑修复 + make_server 更新路由注入
    update_repo = R.get("UPDATE_REPO", "")
    assert update_repo, "replacements.json 需含 UPDATE_REPO（GitHub 用户名/仓库）"
    pyz_e = next(e for e in entries if e["name"] == "PYZ.pyz")
    pyz_bytes = rd(pyz_e)
    t_off = struct.unpack('!i', pyz_bytes[8:12])[0]
    pyz_toc = marshal.loads(pyz_bytes[t_off:])
    typ_s, off_s, len_s = dict(pyz_toc)["server"]
    server_code, sc = patch_consts(marshal.loads(zlib.decompress(pyz_bytes[off_s:off_s + len_s])), server_str)
    old_fn = next(k for k in server_code.co_consts if isinstance(k, types.CodeType) and k.co_name == "ensure_builtin")
    new_fn = build_replacement_function(NEW_ENSURE_BUILTIN_SRC, "ensure_builtin", old_fn)
    server_code = server_code.replace(co_consts=tuple(new_fn if k is old_fn else k for k in server_code.co_consts))
    # 注入一键更新后端：用带 /api/update/* 路由的 make_server 替换原实现
    ms_src = PY_UPDATE_TEMPLATE.replace("__VERSION__", a.version).replace("__REPO__", update_repo)
    old_ms = next(k for k in server_code.co_consts if isinstance(k, types.CodeType) and k.co_name == "make_server")
    new_ms = build_replacement_function(ms_src, "make_server", old_ms)
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

    # 4) 前端
    update_repo = R.get("UPDATE_REPO", "")
    assert update_repo, "replacements.json 需含 UPDATE_REPO（GitHub 用户名/仓库）"
    new_blobs = {}
    for e in entries:
        n = e["name"].lower().replace("\\", "/")
        if n == "static/index.html":
            html = rd(e).decode("utf-8")
            for old, new in R["HTML_REPL"]:
                assert old in html, "HTML anchor missing: %r" % old[:40]
                html = html.replace(old, new)
            new_blobs[e["name"]] = html.encode("utf-8")
        elif n == "static/app.js":
            js = rd(e).decode("utf-8")
            js = js + (JS_UPDATE_TEMPLATE.replace("__VERSION__", a.version).replace("__REPO__", update_repo))
            new_blobs[e["name"]] = js.encode("utf-8")
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


if __name__ == "__main__":
    main()
