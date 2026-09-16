#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
feature_backend.py —— 统一的「功能后端」模板：替换母版 server.make_server。

包含：
  A) 母版 make_server 原有能力（完整保留）：
     qn_* 系列 = Qoder CN（~/.qoder-cn/settings.json 的 BYOK providers 读写）
     通过 monkey-patch Handler.do_GET/do_POST 挂 /api/qodercn/* 路由。
  B) 新增能力：
     q2_*  = Qoder 桌面版新版自定义模型（~/.qoder/settings.json，格式与 CN 一致）
     zc_*  = ZCode（~/.zcode/v2/config.json provider 导入 / 启用切换 / 删除 / 列表）
     tw_*  = TRAE Work CN（state.vscdb model_list_map 列表 / 启用切换 / 删除；
            Key 为 Trae 私有加密，导入仍走剪贴板辅助）
     /api/targets 与扩展 /api/state —— 前端「导入目标管理」界面数据源
     /api/update/* —— 一键更新（UPDATE_ENABLED 为 False 时返回不支持）

本文件被 repack.py（API Switch 发布版）与 _work/feature_pack.py（桌面端母版）共用。
"""

FEATURE_SERVER_SRC = r'''
def make_server():
    import hashlib
    import uuid as _uuid

    # ---- 更新模块参数（repack 时由模板替换） ----
    APP_VERSION = "__VERSION__"
    UPDATE_REPO = "__REPO__"
    UPDATE_ENABLED = __UPDATE_ENABLED__

    UPD = {"stage": "idle", "detail": "", "got": 0, "total": 0,
           "latest": "", "url": "", "asset": "", "asset_url": "", "digest": ""}
    UPD_LOCK = threading.Lock()

    # =====================================================================
    # 通用小工具
    # =====================================================================
    def _proxy_opener():
        try:
            px = get_proxy()
        except Exception:
            px = None
        if px:
            return urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": px, "https": px}))
        return urllib.request.build_opener()

    def _net_open(req, timeout):
        """按应用代理发起请求；代理失败（限流 403 / 连接错误等）时回退直连重试一次。

        背景：代理多为共享出口 IP，匿名访问 api.github.com 每小时仅 60 次，
        极易 403 rate limit；直连通常可用。没有回退会导致静默更新检查失败、
        用户收不到新版本提示。
        注意两点：
        1. urllib 的 ProxyHandler 会调用 req.set_proxy() 原地改写 Request
           （host 变为代理地址），因此重试必须用全新的 Request。
        2. 只调用一次 get_proxy()，用返回值同时构造代理/直连两个 opener，
           避免二次调用因数据目录锁等偶发异常被吞掉后丢失回退路径。"""
        try:
            px = get_proxy()
        except Exception:
            px = None
        if px:
            # 应用内配置了代理：先走应用代理，失败回退直连
            openers = [urllib.request.build_opener(
                           urllib.request.ProxyHandler({"http": px, "https": px})),
                       urllib.request.build_opener(
                           urllib.request.ProxyHandler({}))]  # 显式直连
        else:
            # 未配置应用代理：默认 opener 会用系统代理（含注册表/WPAD 设置），
            # 系统代理失败（共享出口 IP 触发 GitHub 匿名限流 403 等）同样回退直连
            openers = [urllib.request.build_opener(),
                       urllib.request.build_opener(
                           urllib.request.ProxyHandler({}))]
        last = None
        for i, op in enumerate(openers):
            try:
                if i:
                    # 重试必须换全新 Request：首个 opener 失败时可能已把 req
                    # 的 host 改写为代理地址（ProxyHandler.set_proxy 副作用）
                    fresh = urllib.request.Request(
                        req.full_url, headers=dict(req.headers),
                        data=req.data, method=req.get_method())
                else:
                    fresh = req
                return op.open(fresh, timeout=timeout)
            except Exception as e:
                last = e
                if i < len(openers) - 1:
                    try:
                        time.sleep(0.3)
                    except Exception:
                        pass
        raise last

    def _ver_tuple(s):
        s = re.sub(r"^[vV]", "", str(s or "").strip())
        out = []
        for part in s.split("."):
            m = re.match(r"\d+", part)
            out.append(int(m.group()) if m else 0)
        while len(out) < 3:
            out.append(0)
        return tuple(out[:3])

    # =====================================================================
    # A) Qoder CN —— 与母版等价（~/.qoder-cn/settings.json）
    # =====================================================================
    _QODER_DIRS = (".qoder-cn",)
    _QODER_PROCS = ("Qoder CN.exe", "Qoder.exe")

    def qn_candidates(nm=_QODER_DIRS):
        return [os.path.join(HOME, x, "settings.json") for x in nm]

    def qn_config_path(nm=_QODER_DIRS):
        for pth in qn_candidates(nm):
            if not os.path.exists(pth):
                continue
            try:
                with open(pth, encoding="utf-8") as f:
                    obj = json.load(f)
                provs = obj.get("providers") if isinstance(obj, dict) else None
                if isinstance(provs, dict) and provs:
                    return pth
            except Exception:
                pass
        if os.path.exists(qn_candidates(nm)[0]):
            return qn_candidates(nm)[0]
        for x in nm:
            d = os.path.join(HOME, x)
            if os.path.isdir(d):
                return os.path.join(d, "settings.json")
        return qn_candidates(nm)[0]

    def qn_installed(nm=_QODER_DIRS):
        pth = qn_config_path(nm)
        return os.path.exists(pth) or os.path.isdir(os.path.dirname(pth))

    def qn_running(procs=_QODER_PROCS):
        try:
            return any(process_running(x) for x in procs)
        except Exception:
            return False

    def qn_load(nm=_QODER_DIRS):
        pth = qn_config_path(nm)
        if not os.path.exists(pth):
            return {}
        with open(pth, encoding="utf-8") as f:
            obj = json.load(f)
        if not isinstance(obj, dict):
            raise ValueError("settings.json 顶层不是对象")
        return obj

    def qn_read_providers(nm=_QODER_DIRS):
        obj = qn_load(nm)
        provs = obj.get("providers")
        if not isinstance(provs, dict):
            return []
        out = []
        for pid, pv in provs.items():
            if not isinstance(pv, dict):
                continue
            models = []
            for m in pv.get("models") or []:
                if not isinstance(m, dict):
                    continue
                cap = m.get("capabilities") if isinstance(m.get("capabilities"), dict) else {}
                th = cap.get("thinking") if isinstance(cap.get("thinking"), dict) else {}
                models.append({
                    "model": m.get("model"),
                    "displayName": m.get("displayName") or m.get("model"),
                    "contextWindow": m.get("contextWindow"),
                    "maxOutputTokens": m.get("maxOutputTokens"),
                    "vision": bool(cap.get("vision")),
                    "reasoning": bool(th),
                })
            out.append({
                "id": pid,
                "baseUrl": pv.get("baseUrl"),
                "protocol": pv.get("protocol"),
                "type": pv.get("type"),
                "authType": pv.get("authType"),
                "defaultModel": pv.get("model"),
                "models": models,
            })
        return out

    def qn_write(obj, nm=_QODER_DIRS):
        pth = qn_config_path(nm)
        d = os.path.dirname(pth)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        if os.path.exists(pth):
            _backup(pth)
        tmp = pth + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, pth)

    def qn_norm_base(u):
        s = (u or "").strip().rstrip("/")
        if s.endswith("/v1"):
            s = s[:-3].rstrip("/")
        return s

    def qn_import(provider_id, models, nm=_QODER_DIRS):
        if not models:
            raise ValueError("请至少选择一个要导入的模型")
        with LOCK:
            data = load_data()
            p = find_provider(data, provider_id)
        if not p:
            raise ValueError("供应商不存在")
        api_key = p.get("api_key")
        if not api_key:
            raise ValueError("该供应商未保存 API Key")
        base_url = (p.get("base_url") or "").strip()
        if not base_url:
            raise ValueError("该供应商未填写 Base URL")
        protocol = (p.get("wire_api") or "responses") == "responses" and "openai-responses" or "openai"
        obj = qn_load(nm)
        provs = obj.get("providers")
        if not isinstance(provs, dict):
            provs = {}
        target_id = None
        for pid, pv in provs.items():
            if not isinstance(pv, dict):
                continue
            if qn_norm_base(pv.get("baseUrl")) == qn_norm_base(base_url):
                target_id = pid
                break
        if target_id is None:
            target_id = "qoder-custom-" + str(_uuid.uuid4())
            entry = {}
        else:
            entry = dict(provs.get(target_id)) if isinstance(provs.get(target_id), dict) else {}
        entry["baseUrl"] = base_url
        entry["apiKey"] = api_key
        entry["type"] = "openai-compatible"
        entry["protocol"] = protocol
        entry["authType"] = "bearer"
        existing = {}
        for m in entry.get("models") or []:
            if isinstance(m, dict) and m.get("model"):
                existing[m["model"]] = m
        imported = []
        skipped = []
        ordered = []
        chosen = []
        for item in models:
            name = item.get("model") if isinstance(item, dict) else item
            if not name:
                continue
            chosen.append(name)
            if name in existing:
                skipped.append({"model": name, "reason": "已存在"})
                ordered.append(existing.pop(name))
                continue
            me = {"model": name, "displayName": name}
            caps = {}
            if isinstance(item, dict):
                if item.get("contextWindow"):
                    me["contextWindow"] = int(item["contextWindow"])
                if item.get("maxOutputTokens"):
                    me["maxOutputTokens"] = int(item["maxOutputTokens"])
                caps["vision"] = bool(item.get("vision"))
                if item.get("reasoning"):
                    caps["thinking"] = {"modes": ["enabled"], "supportsEffort": True,
                                        "supportedEffortLevels": ["low", "high", "xhigh", "medium"]}
            if caps:
                me["capabilities"] = caps
            ordered.append(me)
            imported.append(name)
        for k in list(existing.keys()):
            ordered.append(existing.pop(k))
        entry["models"] = ordered
        cur_default = entry.get("model")
        if not cur_default or cur_default not in [m.get("model") for m in ordered]:
            cur_default = chosen[0] if chosen else (ordered[0]["model"] if ordered else "")
        entry = {"baseUrl": entry["baseUrl"], "apiKey": entry["apiKey"],
                 "type": entry["type"], "protocol": entry["protocol"],
                 "authType": entry["authType"], "model": cur_default, "models": ordered}
        provs[target_id] = entry
        obj["providers"] = provs
        qn_write(obj, nm)
        return {"imported": imported, "skipped": skipped, "id": target_id}

    def qn_delete(pid, nm=_QODER_DIRS):
        obj = qn_load(nm)
        provs = obj.get("providers")
        if not isinstance(provs, dict) or pid not in provs:
            raise ValueError("未找到该自定义供应商")
        provs.pop(pid, None)
        obj["providers"] = provs
        qn_write(obj, nm)
        return {"id": pid}

    # =====================================================================
    # B1) ZCode —— ~/.zcode/v2/config.json
    # =====================================================================
    ZC_CONFIG = os.path.join(HOME, ".zcode", "v2", "config.json")
    ZC_NAME_MARK = "API·"

    def zc_installed():
        return os.path.isdir(os.path.join(HOME, ".zcode")) or os.path.exists(ZC_CONFIG)

    def zc_running():
        try:
            return bool(process_running("ZCode.exe"))
        except Exception:
            return False

    def zc_load():
        if not os.path.exists(ZC_CONFIG):
            return {}
        with open(ZC_CONFIG, encoding="utf-8") as f:
            obj = json.load(f)
        if not isinstance(obj, dict):
            raise ValueError("config.json 顶层不是对象")
        return obj

    def zc_write(obj):
        d = os.path.dirname(ZC_CONFIG)
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        if os.path.exists(ZC_CONFIG):
            _backup(ZC_CONFIG)
        tmp = ZC_CONFIG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ZC_CONFIG)

    def zc_norm_base(u):
        s = (u or "").strip().rstrip("/")
        low = s.lower()
        if low.endswith("/anthropic") or low.endswith("/v1"):
            return s
        return s + "/v1"

    def zc_read_providers():
        obj = zc_load()
        provs = obj.get("provider")
        if not isinstance(provs, dict):
            return []
        out = []
        for pid, pv in provs.items():
            if not isinstance(pv, dict) or str(pv.get("source")) != "custom":
                continue
            if pid.startswith("builtin:"):
                continue
            models = []
            mm = pv.get("models")
            if isinstance(mm, dict):
                for mid, mv in mm.items():
                    if not isinstance(mv, dict):
                        continue
                    lim = mv.get("limit") if isinstance(mv.get("limit"), dict) else {}
                    rea = mv.get("reasoning") if isinstance(mv.get("reasoning"), dict) else {}
                    models.append({
                        "model": mid,
                        "displayName": (mv.get("name") or mid),
                        "contextWindow": lim.get("context"),
                        "maxOutputTokens": lim.get("output"),
                        "reasoning": bool(rea.get("enabled")),
                    })
            opt = pv.get("options") if isinstance(pv.get("options"), dict) else {}
            out.append({
                "id": pid,
                "name": pv.get("name"),
                "baseUrl": opt.get("baseURL"),
                "kind": pv.get("kind"),
                "enabled": bool(pv.get("enabled")),
                "hasKey": bool(opt.get("apiKey")),
                "models": models,
                "managed": str(pv.get("name") or "").startswith(ZC_NAME_MARK),
            })
        return out

    def zc_import(provider_id, models):
        if not models:
            raise ValueError("请至少选择一个要导入的模型")
        with LOCK:
            data = load_data()
            p = find_provider(data, provider_id)
        if not p:
            raise ValueError("供应商不存在")
        api_key = p.get("api_key")
        if not api_key:
            raise ValueError("该供应商未保存 API Key")
        base_url = (p.get("base_url") or "").strip()
        if not base_url:
            raise ValueError("该供应商未填写 Base URL")
        obj = zc_load()
        provs = obj.get("provider")
        if not isinstance(provs, dict):
            provs = {}
        # 名称命中复用同一 provider（避免重复导入产生多条）
        pname = ZC_NAME_MARK + (p.get("name") or provider_id)
        target_id = None
        for pid, pv in provs.items():
            if isinstance(pv, dict) and pv.get("name") == pname and str(pv.get("source")) == "custom":
                target_id = pid
                break
        if target_id is None:
            target_id = str(_uuid.uuid4())
            entry = {}
        else:
            entry = dict(provs.get(target_id)) if isinstance(provs.get(target_id), dict) else {}
        entry["name"] = pname
        entry["kind"] = "anthropic" if "/anthropic" in base_url.lower() else "openai"
        opt = entry.get("options") if isinstance(entry.get("options"), dict) else {}
        opt["apiKey"] = api_key
        opt["baseURL"] = zc_norm_base(base_url)
        entry["options"] = opt
        entry["enabled"] = True
        entry["source"] = "custom"
        models_map = entry.get("models") if isinstance(entry.get("models"), dict) else {}
        imported = []
        for item in models:
            name = item.get("model") if isinstance(item, dict) else item
            if not name:
                continue
            mv = models_map.get(name) if isinstance(models_map.get(name), dict) else {}
            lim = mv.get("limit") if isinstance(mv.get("limit"), dict) else {}
            if isinstance(item, dict):
                ctx = int(item.get("contextWindow") or 0) or None
                out = int(item.get("maxOutputTokens") or 0) or None
            else:
                ctx = out = None
            lim = {"context": ctx or (lim.get("context") or 200000),
                   "output": out or (lim.get("output") or 32768)}
            mv["limit"] = lim
            rea = mv.get("reasoning") if isinstance(mv.get("reasoning"), dict) else {}
            is_reason = bool(isinstance(item, dict) and item.get("reasoning")) or bool(rea.get("enabled"))
            mv["reasoning"] = {"enabled": is_reason,
                               "variants": ["low", "high", "max"],
                               "defaultVariant": "max"} if is_reason else {"enabled": False}
            modal = mv.get("modalities") if isinstance(mv.get("modalities"), dict) else {}
            mi = modal.get("input") if isinstance(modal.get("input"), list) else ["text"]
            want_img = bool(isinstance(item, dict) and item.get("vision"))
            if want_img and "image" not in mi:
                mi = mi + ["image"]
            mv["modalities"] = {"input": mi, "output": modal.get("output") or ["text"]}
            mv.setdefault("zcode", {"modified": False, "priority": 99})
            models_map[name] = mv
            imported.append(name)
        entry["models"] = models_map
        # 导入只启用自身；不自动禁用其它供应商（切换由「启用」按钮显式完成）
        provs[target_id] = entry
        obj["provider"] = provs
        zc_write(obj)
        return {"imported": imported, "id": target_id, "name": pname}

    def zc_set_enabled(pid, enabled):
        obj = zc_load()
        provs = obj.get("provider")
        if not isinstance(provs, dict) or pid not in provs:
            raise ValueError("未找到该供应商")
        if pid.startswith("builtin:"):
            raise ValueError("内置供应商不可修改")
        if enabled:
            for k, pv in provs.items():
                if isinstance(pv, dict) and str(pv.get("source")) == "custom":
                    pv["enabled"] = (k == pid)
        else:
            provs[pid]["enabled"] = False
        obj["provider"] = provs
        zc_write(obj)
        return {"id": pid, "enabled": bool(enabled)}

    def zc_delete(pid):
        obj = zc_load()
        provs = obj.get("provider")
        if not isinstance(provs, dict) or pid not in provs:
            raise ValueError("未找到该供应商")
        provs.pop(pid, None)
        obj["provider"] = provs
        zc_write(obj)
        return {"id": pid}

    # =====================================================================
    # B2) TRAE Work CN（TRAE SOLO CN）—— state.vscdb model_list_map
    # =====================================================================
    def tw_exe():
        cands = [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "TRAE SOLO CN", "TRAE SOLO CN.exe"),
            r"D:\TRAE SOLO CN\TRAE SOLO CN.exe",
            r"C:\Program Files\TRAE SOLO CN\TRAE SOLO CN.exe",
            TRAE_EXE,
        ]
        for c in cands:
            if c and os.path.exists(c):
                return c
        return ""

    def tw_data_dir():
        rd = os.environ.get("APPDATA") or os.path.join(HOME, "AppData", "Roaming")
        return os.path.join(rd, "TRAE SOLO CN", "User", "globalStorage", "state.vscdb")

    def tw_installed():
        return bool(tw_exe()) or os.path.isdir(os.path.join(HOME, ".trae-cn"))

    def tw_running():
        try:
            return bool(process_running("TRAE SOLO CN.exe"))
        except Exception:
            return False

    def tw_read_custom():
        db = tw_data_dir()
        if not os.path.exists(db):
            return []
        import sqlite3
        con = sqlite3.connect("file:" + db.replace("\\", "/") + "?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT key, value FROM ItemTable WHERE key LIKE '%AI.agent.model.model_list_map'"
            ).fetchall()
        finally:
            con.close()
        seen = {}
        for key, val in rows:
            try:
                obj = json.loads(val if isinstance(val, str) else val.decode("utf-8", "ignore"))
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            for group in obj.values():
                if not isinstance(group, list):
                    continue
                for m in group:
                    if not isinstance(m, dict):
                        continue
                    if m.get("provider") != "custom_openai_compatible":
                        continue
                    mid = str(m.get("custom_model_id") or m.get("name"))
                    if mid in seen:
                        continue
                    seen[mid] = {
                        "id": mid,
                        "name": m.get("display_name") or m.get("name"),
                        "baseUrl": m.get("base_url"),
                        "status": bool(m.get("status")),
                        "vision": bool(m.get("multimodal")),
                        "hasKey": bool(m.get("ak")),
                    }
        return list(seen.values())

    def tw_toggle(model_id, status):
        if tw_running():
            raise ValueError("TRAE 正在运行，请先完全退出 TRAE 再操作")
        db = tw_data_dir()
        if not os.path.exists(db):
            raise ValueError("未检测到 TRAE Work CN 配置")
        _backup(db)
        import sqlite3
        con = sqlite3.connect(db)
        try:
            rows = con.execute(
                "SELECT key, value FROM ItemTable WHERE key LIKE '%AI.agent.model.model_list_map'"
            ).fetchall()
            changed = False
            for key, val in rows:
                try:
                    obj = json.loads(val if isinstance(val, str) else val.decode("utf-8", "ignore"))
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                dirty = False
                for group in obj.values():
                    if not isinstance(group, list):
                        continue
                    for m in group:
                        if isinstance(m, dict) and str(m.get("custom_model_id") or m.get("name")) == str(model_id):
                            m["status"] = bool(status)
                            dirty = True
                if dirty:
                    changed = True
                    con.execute("INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                                (key, json.dumps(obj, ensure_ascii=False)))
            con.commit()
        finally:
            con.close()
        if not changed:
            raise ValueError("未找到该自定义模型")
        return {"id": model_id, "status": bool(status)}

    def tw_delete(model_id):
        if tw_running():
            raise ValueError("TRAE 正在运行，请先完全退出 TRAE 再操作")
        db = tw_data_dir()
        if not os.path.exists(db):
            raise ValueError("未检测到 TRAE Work CN 配置")
        _backup(db)
        import sqlite3
        con = sqlite3.connect(db)
        try:
            rows = con.execute(
                "SELECT key, value FROM ItemTable WHERE key LIKE '%AI.agent.model.model_list_map'"
            ).fetchall()
            removed = 0
            for key, val in rows:
                try:
                    obj = json.loads(val if isinstance(val, str) else val.decode("utf-8", "ignore"))
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                dirty = False
                for gname, group in obj.items():
                    if not isinstance(group, list):
                        continue
                    keep = []
                    for m in group:
                        if isinstance(m, dict) and str(m.get("custom_model_id") or m.get("name")) == str(model_id):
                            removed += 1
                            dirty = True
                            continue
                        keep.append(m)
                    obj[gname] = keep
                if dirty:
                    con.execute("INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                                (key, json.dumps(obj, ensure_ascii=False)))
            con.commit()
        finally:
            con.close()
        if not removed:
            raise ValueError("未找到该自定义模型")
        return {"id": model_id}

    def tw_prepare(provider_id):
        """TRAE Work CN 导入辅助：把供应商信息写入剪贴板并启动 TRAE。"""
        exe = tw_exe()
        if not exe:
            raise ValueError("未检测到 TRAE Work CN（TRAE SOLO CN）")
        with LOCK:
            data = load_data()
            p = find_provider(data, provider_id)
        if not p:
            raise ValueError("供应商不存在")
        lines = ["__BRAND__ - TRAE 自定义模型信息", "=" * 36,
                 "Base URL : %s" % p["base_url"],
                 "API Key  : %s" % p.get("api_key", "")]
        for m in (p.get("models") or [p.get("model")] if p.get("model") else []):
            lines.append("模型名称  : %s" % m)
        lines += ["=" * 36,
                  "在 TRAE 中：设置 → 模型 / 自定义模型 → 添加，",
                  "供应商选 OpenAI 兼容，逐一粘贴以上信息。",
                  "注：TRAE 对 API Key 做私有加密存储，无法由外部工具写入。"]
        text = "\n".join(lines)
        subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard", "-Value", text],
                       capture_output=True, creationflags=CREATE_NO_WINDOW, check=False)
        subprocess.Popen([exe], creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        return {"ok": True, "clipboard": True, "exe": exe}

    # =====================================================================
    # Qoder 桌面版（新版）—— ~/.qoder/settings.json
    # =====================================================================
    _Q2_DIRS = (".qoder",)

    def q2_nm():
        return _Q2_DIRS

    def q2_installed():
        return qn_installed(_Q2_DIRS)

    def q2_running():
        return qn_running(("Qoder.exe",))

    def q2_list():
        return {"ok": True, "file": qn_config_path(_Q2_DIRS),
                "installed": q2_installed(), "running": q2_running(),
                "providers": qn_read_providers(_Q2_DIRS)}

    def q2_import(provider_id, models):
        r = qn_import(provider_id, models, _Q2_DIRS)
        r["file"] = qn_config_path(_Q2_DIRS)
        return r

    # =====================================================================
    # /api/state 扩展 + 目标清单
    # =====================================================================
    def _target_info():
        try:
            t_run = process_running("TRAE SOLO CN.exe")
        except Exception:
            t_run = False
        t_inst = tw_installed()
        zc_inst = zc_installed()
        try:
            zc_run = process_running("ZCode.exe")
        except Exception:
            zc_run = False
        return {
            "codex": {"installed": os.path.isdir(CODEX_DIR) or os.path.exists(CONFIG_FILE),
                      "running": codex_running()},
            "qoder": {"installed": q2_installed(), "running": q2_running(),
                      "file": qn_config_path(_Q2_DIRS)},
            "qodercn": {"installed": qn_installed(_QODER_DIRS), "running": qn_running(),
                        "file": qn_config_path(_QODER_DIRS)},
            "trae": {"installed": t_inst, "running": t_run, "exe": tw_exe()},
            "zcode": {"installed": zc_inst, "running": zc_run, "file": ZC_CONFIG},
        }

    def _state_json():
        with LOCK:
            data = load_data()
        active = detect_active()
        masked = []
        for p in data["codex"]["providers"]:
            q = dict(p)
            q["api_key"] = (p.get("api_key") or "")[:8] + "***" if p.get("api_key") else ""
            masked.append(q)
        return {
            "providers": masked, "active": active,
            "codex_running": codex_running(), "config_file": CONFIG_FILE,
            "base_ok": os.path.exists(BASE_FILE),
            "settings": data.get("settings") or {},
            "targets": _target_info(),
            "qoder_imports": (data.get("qoder") or {}).get("imports", []),
            "trae_imports": (data.get("trae") or {}).get("imports", []),
        }

    # =====================================================================
    # 更新检查（后端代理）
    # =====================================================================
    def _upd_check():
        if not UPDATE_ENABLED:
            return {"ok": False, "error": "本版本未启用在线更新"}
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "APISwitch-updater"}
        tok = os.environ.get("GITHUB_TOKEN") or ""
        if tok:
            headers["Authorization"] = "Bearer " + tok
        req = urllib.request.Request(
            "https://api.github.com/repos/" + UPDATE_REPO + "/releases/latest", headers=headers)
        with _net_open(req, 15) as r:
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
                       asset_url=asset_url, digest=digest, got=0, total=size)
        return {"ok": True, "current": APP_VERSION, "latest": tag, "has_update": has,
                "url": j.get("html_url") or "", "asset": name, "size": size}

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
            with _net_open(req, 60) as r, open(part, "wb") as f:
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
            if digest and h.hexdigest().lower() != digest.split(":", 1)[-1].lower():
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
        bat = os.path.join(DATA_DIR, "update_apply.bat")
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

    def _uninstall_cleanup(restore_original=True):
        """卸载并清除数据：
        1) 用首次修改前的备份还原 Codex 原始配置（config.original.toml / auth.original.json）
        2) 删除本工具数据目录（供应商库，含 DPAPI 加密的 Key）——不可恢复
        3) 删除工具维护的 Codex 模型规格缓存 codex-models.json
        各目标软件（Qoder / ZCode / TRAE 等）自己配置文件里已导入的模型不属于本工具，不触碰。
        执行后前端应提示用户关闭并删除 exe 本体。"""
        result = {"ok": True, "restored": False, "removed": [], "errors": []}

        def rm(path):
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    result["removed"].append(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path)
                    result["removed"].append(path)
            except Exception as e:
                result["ok"] = False
                result["errors"].append(os.path.basename(path) + ": " + str(e)[:100])

        # 1) 还原 Codex 原始配置（备份存在才动；不存在说明从未切换过，无需处理）
        if restore_original:
            try:
                has_backup = os.path.exists(BASE_FILE) or os.path.exists(AUTH_BACKUP_FILE)
                in_use = os.path.exists(CONFIG_FILE)
                if has_backup and in_use:
                    apply_original()
                    result["restored"] = True
            except Exception as e:
                result["ok"] = False
                result["errors"].append("restore: " + str(e)[:120])

        # 2) 工具数据目录（供应商库，全部加密数据随之销毁）
        if os.path.isdir(DATA_DIR):
            rm(DATA_DIR)

        # 3) 模型规格缓存
        rm(os.path.join(HOME, ".codex", "codex-models.json"))

        return result

    # =====================================================================
    # 路由挂载
    # =====================================================================
    _orig_get = Handler.do_GET
    _orig_post = Handler.do_POST

    def _api_get(self, path):
        if path == "/api/state":
            self._send(200, _state_json())
            return True
        if path == "/api/targets":
            self._send(200, {"ok": True, "targets": _target_info(), "version": APP_VERSION})
            return True
        if path == "/api/qodercn/list":
            self._send(200, {"ok": True, "file": qn_config_path(_QODER_DIRS),
                             "installed": qn_installed(_QODER_DIRS), "running": qn_running(),
                             "providers": qn_read_providers(_QODER_DIRS)})
            return True
        if path == "/api/qoder2/list":
            self._send(200, q2_list())
            return True
        if path == "/api/zcode/list":
            self._send(200, {"ok": True, "file": ZC_CONFIG, "installed": zc_installed(),
                             "running": zc_running(), "providers": zc_read_providers()})
            return True
        if path == "/api/trae/models":
            self._send(200, {"ok": True, "installed": tw_installed(), "running": tw_running(),
                             "exe": tw_exe(), "models": tw_read_custom()})
            return True
        if path == "/api/update/check":
            try:
                self._send(200, _upd_check())
            except Exception as e:
                self._send(200, {"ok": False, "error": str(e)[:200]})
            return True
        if path == "/api/update/status":
            with UPD_LOCK:
                self._send(200, dict(UPD))
            return True
        return False

    def _api_post(self, path, body):
        if path == "/api/qodercn/import":
            r = qn_import(body.get("providerId"), body.get("models") or [], _QODER_DIRS)
            r["ok"] = True
            self._send(200, r)
            return True
        if path == "/api/qodercn/delete":
            r = qn_delete(body.get("id"), _QODER_DIRS)
            r["ok"] = True
            self._send(200, r)
            return True
        if path == "/api/qoder2/import":
            r = q2_import(body.get("providerId"), body.get("models") or [])
            r["ok"] = True
            self._send(200, r)
            return True
        if path == "/api/qoder2/delete":
            r = qn_delete(body.get("id"), _Q2_DIRS)
            r["ok"] = True
            self._send(200, r)
            return True
        if path == "/api/zcode/import":
            r = zc_import(body.get("providerId"), body.get("models") or [])
            r["ok"] = True
            self._send(200, r)
            return True
        if path == "/api/zcode/enable":
            r = zc_set_enabled(body.get("id"), bool(body.get("enabled")))
            r["ok"] = True
            self._send(200, r)
            return True
        if path == "/api/zcode/delete":
            r = zc_delete(body.get("id"))
            r["ok"] = True
            self._send(200, r)
            return True
        if path == "/api/trae/models/delete":
            r = tw_delete(body.get("id"))
            r["ok"] = True
            self._send(200, r)
            return True
        if path == "/api/trae/models/toggle":
            r = tw_toggle(body.get("id"), bool(body.get("status")))
            r["ok"] = True
            self._send(200, r)
            return True
        if path == "/api/trae/prepare2":
            r = tw_prepare(body.get("providerId"))
            self._send(200, r)
            return True
        if path == "/api/update/start":
            if not UPDATE_ENABLED:
                self._send(200, {"ok": False, "error": "本版本未启用在线更新"})
                return True
            threading.Thread(target=_upd_download, daemon=True).start()
            self._send(200, {"ok": True})
            return True
        if path == "/api/update/apply":
            self._send(200, _upd_apply())
            return True
        if path == "/api/uninstall":
            self._send(200, _uninstall_cleanup(body.get("restoreOriginal", True)))
            return True
        return False

    MY_POST_PATHS = {
        "/api/qodercn/import", "/api/qodercn/delete",
        "/api/qoder2/import", "/api/qoder2/delete",
        "/api/zcode/import", "/api/zcode/enable", "/api/zcode/delete",
        "/api/trae/models/delete", "/api/trae/models/toggle", "/api/trae/prepare2",
        "/api/update/start", "/api/update/apply", "/api/uninstall",
    }

    def _wrapped_get(self):
        p = getattr(self, "path", "").split("?", 1)[0]
        if p.startswith("/api/"):
            if not self._host_allowed():
                self._send(403, {"error": "forbidden"})
                return
            try:
                if _api_get(self, p):
                    return
            except Exception as e:
                self._send(200, {"ok": False, "error": str(e)[:300]})
                return
        _orig_get(self)

    def _wrapped_post(self):
        p = getattr(self, "path", "").split("?", 1)[0]
        if p not in MY_POST_PATHS:
            # 非本模块路由：交回原始实现（原始 do_POST 自行读取请求体，禁止提前消费）
            _orig_post(self)
            return
        if not self._host_allowed():
            self._send(403, {"error": "forbidden"})
            return
        try:
            body = self._body() or {}
            _api_post(self, p, body)
        except Exception as e:
            self._send(200, {"ok": False, "error": str(e)[:300]})

    Handler.do_GET = _wrapped_get
    Handler.do_POST = _wrapped_post

    # 单实例保护：Windows 上 SO_REUSEADDR 允许多进程同时绑定同一端口，
    # 请求会被随机分发（实测会造成双实例数据错乱）。禁用地址复用，
    # 让第二个实例绑定失败并退出（make_server 返回 None → main 直接退出）。
    class _SingleInstanceServer(ThreadingHTTPServer):
        allow_reuse_address = False

    try:
        return _SingleInstanceServer(("127.0.0.1", 8765), Handler)
    except OSError:
        return None
'''


def build_make_server_code(version="0.0.0", repo="", update_enabled=False, brand="API Switch"):
    """返回编译好的 make_server 代码对象（供替换进 server 模块）。

    嵌套的 qn_/q2_/zc_/tw_ 辅助通过闭包引用 make_server 内的 `import uuid as _uuid`。
    """
    import types
    src = FEATURE_SERVER_SRC.replace("__VERSION__", version).replace("__REPO__", repo)
    src = src.replace("__UPDATE_ENABLED__", "True" if update_enabled else "False")
    src = src.replace("__BRAND__", brand)
    mod = compile(src, "<features>", "exec")
    fn = next(k for k in mod.co_consts if isinstance(k, types.CodeType) and k.co_name == "make_server")
    return fn
