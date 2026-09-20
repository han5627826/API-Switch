/* 前端逻辑 —— 所有目标页共用供应商库 */
"use strict";

let state = { providers: [], active: null, codex_running: false,
              targets: {}, qoder_imports: [], trae_imports: [] };
let selected = null;          // 当前详情页展示的供应商 id
let editingId = null;         // 弹窗正在编辑的 id（null=新增）
let draftModels = [];         // 弹窗内模型集合（对象 {id, on}）
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

/* ---------- 模型规格自动识别（上下文窗口 / 最大输出） ----------
   内置表来自 models.dev（打包时快照）；启动后再在线拉取最新数据覆盖。 */
const LIMITS_RAW = "__LIMITS_RAW__";
const LIM = { bare: {}, norm: {} };
let limitAuto = true;          // false = 用户手动改过数值，停止自动覆盖
let limitsOnlineLoaded = false;

function normKey(s) { return s.toLowerCase().replace(/[^a-z0-9]/g, ""); }

function addLimit(id, ctx, out, flags, src) {
  if (!ctx) return;
  const bare = id.includes("/") ? id.split("/").pop() : id;
  for (const k of [normKey(bare), normKey(id)]) {
    const cur = LIM.norm[k];
    if (!cur || ctx > cur.ctx) LIM.norm[k] = { ctx, out, flags, src };
  }
}

(function parseBuiltinLimits() {
  for (const row of LIMITS_RAW.split("|")) {
    const p = row.split(":");
    if (p.length < 4) continue;
    addLimit(p[0], +p[1], +p[2], +p[3], "内置");
  }
})();

function lookupLimit(modelId) {
  if (!modelId) return null;
  const bare = (modelId.includes("/") ? modelId.split("/").pop() : modelId);
  const nb = normKey(bare);
  if (LIM.norm[nb]) return LIM.norm[nb];
  const n = normKey(modelId);
  if (LIM.norm[n]) return LIM.norm[n];
  let best = null;                       // 最长前缀匹配（双方互为前缀）
  for (const k of Object.keys(LIM.norm)) {
    if (n.startsWith(k) || k.startsWith(n)) {
      const score = Math.min(n.length, k.length);
      if (score >= 5 && (!best || score > best.score)) best = { score, hit: LIM.norm[k] };
    }
  }
  return best ? best.hit : null;
}

function detectLimits(modelId) {
  if (!modelId) return;
  const hint = $("#f-limits-hint");
  if (!hint) return;
  const hit = lookupLimit(modelId);
  if (hit) {
    $("#f-ctx").value = hit.ctx;
    $("#f-max").value = hit.out || 32768;
    hint.textContent =
      `✓ 已自动识别「${modelId}」支持上限：上下文 ${hit.ctx} / 输出 ${hit.out || "?"}（${hit.src}规格表，可手动修改）`;
    hint.style.cssText = "";                       // 恢复默认绿色识别提示样式
  } else {
    hint.textContent = `未收录「${modelId}」的公开规格，保留当前值，可手动修改`;
    hint.style.borderColor = "var(--line)";
    hint.style.background = "var(--field)";
    hint.style.color = "var(--muted)";
  }
}

async function loadModelLimitsOnline() {
  if (limitsOnlineLoaded) return;
  limitsOnlineLoaded = true;
  try {
    const r = await fetch("https://models.dev/models.json");
    if (!r.ok) return;
    const j = await r.json();
    for (const [id, mv] of Object.entries(j)) {
      const lim = mv && mv.limit;
      if (lim && lim.context) {
        const f = (mv.reasoning ? 1 : 0) | (mv.attachment ? 2 : 0);
        addLimit(id, lim.context, lim.output || 0, f, "在线");
      }
    }
    if (!$("#modal-mask").classList.contains("hidden") && limitAuto) {
      detectLimits($("#f-model").value);
    }
  } catch (e) { /* 离线：使用内置表 */ }
}

async function api(path, body) {
  const opt = body ? {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  } : {};
  const r = await fetch(path, opt);
  return r.json();
}

function toast(msg, err) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = err ? "err" : "";
  t.classList.remove("hidden");
  clearTimeout(t._tm);
  t._tm = setTimeout(() => t.classList.add("hidden"), 3200);
}

async function refresh(keepSelected) {
  state = await api("/api/state");
  if (!keepSelected || !state.providers.some((p) => p.id === selected)) {
    selected = state.active || (state.providers[0] && state.providers[0].id);
  }
  renderHome();
  render();
  renderQoder2();
  renderQodercn(false);
  renderZcode();
  renderTrae();
  renderBanners();
  showAppVersion();
  if (state.legacy_pending && !legacyHandled) showLegacyDlg(state.legacy_pending);
}

/* ---------------- 标题版本号 ---------------- */
function showAppVersion() {
  const el = $("#app-ver");
  if (!el) return;
  const v = String(state.version || "").trim();
  el.textContent = v ? (v.startsWith("v") || v.startsWith("V") ? v : "v" + v) : "";
}

/* ---------------- 旧版供应商导入确认 ---------------- */
let legacyHandled = false;

function showLegacyDlg(list) {
  const box = $("#legacy-list");
  if (!box) return;
  box.innerHTML = (list || []).map((p) =>
    `<div class="legacy-item"><span class="legacy-name">${esc(p.name)}</span>` +
    `<span class="badge">${p.models || 0} 模型</span></div>`).join("");
  $("#legacy-mask").classList.remove("hidden");
}

async function resolveLegacy(keep) {
  const r = await api("/api/legacy/resolve", { action: keep ? "keep" : "reset" });
  legacyHandled = true;
  $("#legacy-mask").classList.add("hidden");
  if (!r.ok) { toast(r.error || "操作失败", true); return; }
  toast(keep ? "已保留旧版本供应商" : "已删除所有添加的供应商，恢复默认");
  if (!keep) selected = "original";
  await refresh(true);
}

/* ---------------- 顶部模块 Tab ---------------- */
$$("#tabs .tab").forEach((btn) => {
  btn.onclick = () => switchTab(btn.dataset.view);
});
function switchTab(view) {
  $$("#tabs .tab").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === view);
  });
  $$(".view").forEach((v) => v.classList.add("hidden"));
  $("#view-" + view).classList.remove("hidden");
  $("#scroller").scrollTop = 0;
  if (view === "codex") render();
  if (view === "qoder2") loadQoder2List();
  if (view === "qodercn") loadQodercn();
  if (view === "zcode") loadZcode();
  if (view === "trae") loadTraeModels();
  if (view === "targets") renderHome();
}

/* ---------------- 目标管理（首页） ---------------- */
const TARGET_DEFS = [
  { key: "codex", name: "Codex / ChatGPT 桌面版", tab: "codex",
    desc: "写入 ~/.codex/config.toml，直接切换生效供应商",
    how: "添加供应商 → 启用此配置" },
  { key: "qoder", name: "Qoder（桌面版）", tab: "qoder2",
    desc: "写入 ~/.qoder/settings.json（新版自定义模型 BYOK 格式）",
    how: "Qoder 页 → 勾选模型 → 一键导入（需先退出 Qoder）" },
  { key: "qodercn", name: "Qoder CN / CLI", tab: "qodercn",
    desc: "写入 ~/.qoder-cn/settings.json 的 providers（原生 BYOK 格式）",
    how: "Qoder CN 页 → 勾选模型 → 一键导入" },
  { key: "zcode", name: "ZCode", tab: "zcode",
    desc: "写入 ~/.zcode/v2/config.json，支持导入与一键启用切换",
    how: "ZCode 页 → 勾选模型 → 导入；列表中点「启用」即切换" },
  { key: "trae", name: "TRAE Work CN", tab: "trae",
    desc: "Key 为 TRAE 私有加密，采用剪贴板辅助导入；支持查看/停用/删除",
    how: "TRAE 页 → 复制模型信息并启动 TRAE → 粘贴添加" },
];

function customProviders() {
  return state.providers.filter((p) => p.id !== "original");
}

function renderHome() {
  renderStats();
  renderProviderGrid();
  renderTargetsList();
  renderCodexConfig();
}

function renderStats() {
  const provs = customProviders();
  $("#stat-providers").textContent = provs.length;
  $("#stat-models").textContent = provs.reduce((n, p) => n + (p.models || []).length, 0);
  const t = state.targets || {};
  const found = TARGET_DEFS.filter((d) => (t[d.key] || {}).installed).length;
  $("#stat-targets").textContent = found + "/" + TARGET_DEFS.length;
}

function renderProviderGrid() {
  const grid = $("#provider-grid");
  if (!grid) return;
  grid.innerHTML = "";
  const t = state.targets || {};
  const importable = TARGET_DEFS.filter((d) => d.key !== "codex" && (t[d.key] || {}).installed).length;
  for (const p of state.providers) {
    const isOriginal = p.id === "original";
    const isActive = p.id === state.active;
    const card = document.createElement("div");
    card.className = "pv-card" + (p.id === selected ? " selected" : "");
    let badge = "";
    if (isActive) badge = '<span class="badge badge-ok">使用中</span>';
    else if (isOriginal) badge = '<span class="badge">原始</span>';
    else if (importable > 0) badge = `<span class="badge badge-brand">可导入 ${importable} 处</span>`;
    const models = (p.models || []).length;
    const meta = isOriginal
      ? '<span class="badge">登录凭据</span>'
      : `<span class="badge">${models} 模型</span>` +
        `<span class="badge">${p.wire_api === "chat" ? "Chat" : "Responses"}</span>` +
        (p.context_window ? `<span class="badge">上下文 ${fmtK(p.context_window)}</span>` : "");
    const initial = esc((p.name || "?").slice(0, 2).toUpperCase());
    card.innerHTML = `
      <div class="pv-top">
        <div class="pv-id">
          <div class="pv-avatar ${isOriginal ? "original" : ""}">${initial}</div>
          <span class="pv-name">${esc(p.name)}</span>
        </div>${badge}</div>
      <div class="pv-url mono">${isOriginal ? "ChatGPT 官方账号，原始配置" : esc(p.base_url)}</div>
      <div class="pv-meta">${meta}
        ${isOriginal ? "" : `
        <span class="pv-actions">
          <button class="icon-btn" data-act="edit" title="编辑">✎</button>
          <button class="icon-btn" data-act="del" title="删除">🗑</button>
        </span>`}
      </div>`;
    card.onclick = () => { selected = p.id; renderProviderGrid(); render(); };
    const eb = card.querySelector('[data-act="edit"]');
    if (eb) eb.onclick = (e) => { e.stopPropagation(); openModal(p); };
    const db = card.querySelector('[data-act="del"]');
    if (db) db.onclick = (e) => { e.stopPropagation(); doDelete(p); };
    grid.appendChild(card);
  }
}

function fmtK(n) {
  n = +n || 0;
  return n >= 1000 ? (n % 1000 ? (n / 1000).toFixed(1) : n / 1000) + "K" : String(n);
}

function renderTargetsList() {
  const box = $("#targets-list");
  if (!box) return;
  const t = state.targets || {};
  box.innerHTML = "";
  for (const def of TARGET_DEFS) {
    const info = t[def.key] || {};
    const inst = !!info.installed;
    const row = document.createElement("button");
    row.className = "rowlink" + (inst ? "" : " off");
    const dotColor = inst ? (info.running ? "#059669" : "#0891b2") : "var(--faint)";
    const status = inst ? (info.running ? "运行中" : "已检测到") : "未检测到";
    row.innerHTML = `
      <span class="rl-dot" style="background:${dotColor}"></span>
      <span class="rl-name">${esc(def.name)}</span>
      <span class="rl-note mono">${esc(def.desc)}</span>
      <span class="badge ${inst ? "badge-ok" : "gray"}">${status}</span>
      <span class="rl-arrow">${inst ? "›" : ""}</span>`;
    row.title = "用法：" + def.how;
    if (inst) row.onclick = () => switchTab(def.tab);
    box.appendChild(row);
  }
}

function renderCodexConfig() {
  const box = $("#codex-config");
  if (!box) return;
  const p = state.providers.find((x) => x.id === state.active);
  const models = (p && p.models) || [];
  const chips = models.slice(0, 6).map((m) => `<span class="chip mono">${esc(m)}</span>`).join("") +
    (models.length > 6 ? `<span class="chip mono">+${models.length - 6}</span>` : "");
  box.innerHTML = `
    <div class="cc-head">
      <div style="min-width:0">
        <div class="cc-name">${esc(p ? p.name : "未选择")}
          ${p ? '<span class="badge badge-ok">使用中</span>' : ""}</div>
        <div class="cc-url mono">${p ? (p.id === "original" ? "ChatGPT 官方账号，原始配置" : esc(p.base_url)) : "—"}</div>
      </div>
      <div class="cc-fmt">
        ${p && p.id === "original" ? '<div>登录凭据</div>' : `
        <div>${p ? (p.wire_api === "chat" ? "Chat" : "Responses") + " · " + (p.auth_mode === "authjson" ? "auth.json" : "环境变量") : ""}</div>
        <div>${p ? esc(p.model || (models[0] || "-")) : ""}${p && p.reasoning_effort ? " · " + esc(p.reasoning_effort) : ""}</div>`}
      </div>
    </div>
    ${models.length ? `<div class="cc-models">${chips}</div>` : ""}
    <div class="divider"></div>
    <div class="cc-row"><span class="k">Codex 进程</span><span class="v">
      <span class="dot ${state.codex_running ? "on" : "off"}"></span>${state.codex_running ? "运行中" : "未运行"}</span></div>
    <div class="cc-row"><span class="k">配置写入</span><span class="v mono" title="${esc(state.config_file || '~/.codex/config.toml')}">${esc(state.config_file || "~/.codex/config.toml")}</span></div>
    <div class="cc-actions">
      <button class="btn ghost" id="home-restart">重启 Codex</button>
      <button class="btn primary" id="home-switch">切换配置</button>
    </div>`;
  $("#home-restart").onclick = restartCodex;
  $("#home-switch").onclick = () => switchTab("codex");
}

/* ---------------- 页内横幅（自动识别提示） ---------------- */
function renderBanners() {
  const n = customProviders().length;
  const t = state.targets || {};
  const st = (k) => {
    const i = t[k] || {};
    return i.installed ? (i.running ? "已检测到 · 运行中" : "已检测到 · 未运行") : "未检测到";
  };
  const set = (id, html) => { const el = $(id); if (el) el.innerHTML = html; };
  set("#codex-banner-text",
    `供应商来自 <b>目标管理 · 供应商库</b>，本页自动识别已录入的 <b>${n}</b> 个供应商 —— 添加与编辑请前往目标管理页。`);
  set("#q2-banner",
    `已自动识别供应商库（<b>${n}</b> 个）。选择供应商后勾选模型，一键写入 <span class="mono">~/.qoder/settings.json</span>。`);
  set("#qn-banner",
    `已自动识别供应商库（<b>${n}</b> 个）· 写入 <span class="mono">~/.qoder-cn/settings.json</span> 的 providers。`);
  set("#zc-banner",
    `已自动识别供应商库（<b>${n}</b> 个）· 导入 ZCode 后在列表中直接「启用」切换。`);
  set("#t-banner",
    `已自动识别供应商库（<b>${n}</b> 个）。TRAE Key 为私有加密，仍采用「复制信息 + 手动粘贴」辅助导入。`);
  const qs = $("#q2-status"); if (qs) qs.textContent = "Qoder：" + st("qoder");
  const qns = $("#qn-status"); if (qns) qns.textContent = "Qoder CN：" + st("qodercn");
  const zcs = $("#zc-status"); if (zcs) zcs.textContent = "ZCode：" + st("zcode");
  const ts = $("#t-status"); if (ts) ts.textContent = "TRAE：" + st("trae");
}

/* ---------------- 供应商下拉 + 模型勾选（公用） ---------------- */
function fillProviderSelect(sel) {
  const cur = sel.value;
  sel.innerHTML = "";
  for (const p of customProviders()) {
    const o = document.createElement("option");
    o.value = p.id;
    o.textContent = `${p.name}（${(p.models || []).length} 个模型）`;
    sel.appendChild(o);
  }
  if (cur && state.providers.some((p) => p.id === cur)) sel.value = cur;
}

function providerModels() {
  const pv = state.providers.find((x) => x.id === (providerSel && providerSel.value));
  return (pv && pv.models) || [];
}
let providerSel = null;

function modelMeta(id) {
  const hit = lookupLimit(id);
  return {
    contextWindow: hit ? hit.ctx : 200000,
    maxOutputTokens: hit && hit.out ? hit.out : 32768,
    vision: hit ? !!(hit.flags & 2) : false,
    reasoning: hit ? !!(hit.flags & 1) : false,
  };
}

function renderModelChecks(box) {
  box.innerHTML = "";
  const models = providerModels();
  if (!models.length) {
    box.innerHTML = '<span class="muted">该供应商暂无模型 —— 请在「目标管理 · 供应商库」编辑并获取模型</span>';
    return;
  }
  for (const id of models) {
    const meta = modelMeta(id);
    const item = document.createElement("label");
    item.className = "model-check on";
    item.dataset.mid = id;
    item.innerHTML = `<input type="checkbox" checked> <span class="mono">${esc(id)}</span> ` +
      `<span class="m-meta">${meta.contextWindow}/${meta.maxOutputTokens}${meta.reasoning ? " · 推理" : ""}${meta.vision ? " · 视觉" : ""}</span>`;
    item.onclick = (e) => {
      e.preventDefault();
      item.classList.toggle("on");
      item.querySelector("input").checked = item.classList.contains("on");
    };
    box.appendChild(item);
  }
}

function pickedModels(box) {
  return [...box.querySelectorAll(".model-check")]
    .filter((el) => el.classList.contains("on"))
    .map((el) => Object.assign({ model: el.dataset.mid }, modelMeta(el.dataset.mid)));
}

function renderImportBox(provSel, box, statusEl, importBtn, installed, running) {
  providerSel = provSel;
  fillProviderSelect(provSel);
  renderModelChecks(box);
  importBtn.disabled = !installed || !providerModels().length;
}

/* ---------------- Qoder（桌面版·新版）模块 ---------------- */
function renderQoder2() {
  const t = (state.targets || {}).qoder || {};
  renderImportBox($("#q2-provider"), $("#q2-models"), $("#q2-status"), $("#q2-import"),
    t.installed, t.running);
}

async function loadQoder2List() {
  const box = $("#q2-list");
  box.innerHTML = '<span class="muted">加载中…</span>';
  const r = await api("/api/qoder2/list");
  if (!r.ok) { box.innerHTML = `<span class="muted">${esc(r.error)}</span>`; return; }
  if (!r.providers || !r.providers.length) {
    box.innerHTML = '<span class="muted">settings.json 中暂无自定义供应商</span>'; return;
  }
  box.innerHTML = "";
  for (const p of r.providers) {
    const row = document.createElement("div");
    row.className = "q-item";
    const ms = (p.models || []).map((m) => m.model).join("、") || "-";
    row.innerHTML = `
      <div class="grow">
        <div class="q-name">${esc(p.defaultModel || "?")}</div>
        <div class="q-url mono">${esc(p.baseUrl || "-")} · ${esc(p.protocol || "openai")} · ${esc(p.type || "")}</div>
        <div class="q-url">模型：${esc(ms)}</div>
      </div>
      <button class="btn danger tiny">删除</button>`;
    row.querySelector("button").onclick = async () => {
      if (!(await confirmDlg("从 Qoder settings.json 删除该自定义供应商（含全部模型）？"))) return;
      const res = await api("/api/qoder2/delete", { id: p.id });
      if (res.ok) { toast("已删除"); loadQoder2List(); }
      else toast(res.error || "删除失败", true);
    };
    box.appendChild(row);
  }
}

async function qoder2Import() {
  const models = pickedModels($("#q2-models"));
  if (!models.length) return toast("请至少勾选一个模型", true);
  const btn = $("#q2-import");
  btn.disabled = true; btn.textContent = "导入中…";
  const r = await api("/api/qoder2/import", { providerId: $("#q2-provider").value, models });
  btn.disabled = false; btn.textContent = "一键导入到 Qoder";
  if (r.ok) {
    toast(`已导入 ${r.imported.length} 个模型${r.skipped.length ? `，跳过 ${r.skipped.length} 个已存在` : ""}`);
    loadQoder2List();
  } else toast(r.error || "导入失败", true);
}

/* ---------------- Qoder CN（CLI）模块 ---------------- */
let qnState = { installed: false, running: false, file: "", providers: [] };

async function loadQodercn() {
  const r = await api("/api/qodercn/list");
  const st = $("#qn-status");
  if (!r || !r.ok) {
    if (st) st.textContent = (r && r.error) || "读取失败";
    return;
  }
  qnState = r;
  if (st) {
    st.textContent = !r.installed
      ? "未检测到 Qoder / Qoder CN 配置目录"
      : (r.running ? "⚠ Qoder CN 运行中（新配置在下次对话生效）" : "已就绪：" + (r.file || ""));
  }
  renderQodercnList();
}

function renderQodercn(force) {
  providerSel = $("#qn-provider");
  fillProviderSelect($("#qn-provider"));
  renderQnModels();
  if (force || !renderQodercn._loaded) { renderQodercn._loaded = true; loadQodercn(); }
}

function renderQnModels() {
  const box = $("#qn-models");
  if (!box) return;
  providerSel = $("#qn-provider");
  renderModelChecks(box);
  const t = (state.targets || {}).qodercn || {};
  $("#qn-import").disabled = !t.installed || !providerModels().length;
}

async function qodercnImport() {
  const models = pickedModels($("#qn-models"));
  if (!models.length) return toast("请至少勾选一个模型", true);
  const btn = $("#qn-import");
  btn.disabled = true; btn.textContent = "导入中…";
  const r = await api("/api/qodercn/import", { providerId: $("#qn-provider").value, models });
  btn.disabled = false; btn.textContent = "一键导入到 Qoder CN";
  if (r.ok) {
    toast(`已导入 ${r.imported.length} 个模型${r.skipped.length ? `，跳过 ${r.skipped.length} 个已存在` : ""}`);
    loadQodercn();
  } else toast(r.error || "导入失败", true);
}

function renderQodercnList() {
  const box = $("#qn-list");
  if (!box) return;
  if (!qnState.providers || !qnState.providers.length) {
    box.innerHTML = '<span class="muted">settings.json 中暂无自定义供应商</span>';
    return;
  }
  box.innerHTML = "";
  for (const p of qnState.providers) {
    const row = document.createElement("div");
    row.className = "q-item";
    const ms = (p.models || []).map((m) => m.model).join("、") || "-";
    row.innerHTML = `
      <div class="grow">
        <div class="q-name">${esc(p.defaultModel || "?")}</div>
        <div class="q-url mono">${esc(p.baseUrl || "-")} · ${esc(p.protocol || "openai")} · ${esc(p.type || "")}</div>
        <div class="q-url">模型：${esc(ms)}</div>
      </div>
      <button class="btn danger tiny">删除</button>`;
    row.querySelector("button").onclick = async () => {
      if (!(await confirmDlg("从 settings.json 删除该自定义供应商（含全部模型）？"))) return;
      const res = await api("/api/qodercn/delete", { id: p.id });
      if (res.ok) { toast("已删除"); loadQodercn(); }
      else toast(res.error || "删除失败", true);
    };
    box.appendChild(row);
  }
}

/* ---------------- ZCode 模块 ---------------- */
let zcState = { installed: false, running: false, file: "", providers: [] };

function renderZcode() {
  const t = (state.targets || {}).zcode || {};
  renderImportBox($("#zc-provider"), $("#zc-models"), $("#zc-status"), $("#zc-import"),
    t.installed, t.running);
}

async function loadZcode() {
  const r = await api("/api/zcode/list");
  const st = $("#zc-status");
  if (!r || !r.ok) { if (st) st.textContent = (r && r.error) || "读取失败"; return; }
  zcState = r;
  if (st) {
    st.textContent = !r.installed ? "未检测到 ZCode"
      : (r.running ? "⚠ ZCode 运行中（导入/切换后需重启 ZCode 生效）" : "已就绪：" + (r.file || ""));
  }
  renderZcodeList();
}

function renderZcodeList() {
  const box = $("#zc-list");
  if (!box) return;
  if (!zcState.providers || !zcState.providers.length) {
    box.innerHTML = '<span class="muted">ZCode 中暂无自定义供应商（导入后出现在这里）</span>';
    return;
  }
  box.innerHTML = "";
  for (const p of zcState.providers) {
    const row = document.createElement("div");
    row.className = "q-item";
    const ms = (p.models || []).map((m) => m.model).join("、") || "-";
    row.innerHTML = `
      <div class="grow">
        <div class="q-name">${esc(p.name || p.id)}
          ${p.enabled ? '<span class="badge badge-ok">使用中</span>' : ""}
          ${p.managed ? '<span class="badge gray">由本工具导入</span>' : ""}</div>
        <div class="q-url mono">${esc(p.baseUrl || "-")} · ${esc(p.kind || "")}${p.hasKey ? "" : " · 未保存 Key"}</div>
        <div class="q-url">模型：${esc(ms)}</div>
      </div>
      <button class="btn tiny ${p.enabled ? "ghost" : "primary"}" data-act="enable">${p.enabled ? "停用" : "启用"}</button>
      <button class="btn danger tiny" data-act="del">删除</button>`;
    row.querySelector('[data-act="enable"]').onclick = async () => {
      const res = await api("/api/zcode/enable", { id: p.id, enabled: !p.enabled });
      if (res.ok) { toast(p.enabled ? "已停用（重启 ZCode 生效）" : "已启用（重启 ZCode 生效）"); loadZcode(); }
      else toast(res.error || "操作失败", true);
    };
    row.querySelector('[data-act="del"]').onclick = async () => {
      if (!(await confirmDlg(`从 ZCode 删除供应商「${p.name || p.id}」（含全部模型）？`))) return;
      const res = await api("/api/zcode/delete", { id: p.id });
      if (res.ok) { toast("已删除（重启 ZCode 生效）"); loadZcode(); }
      else toast(res.error || "删除失败", true);
    };
    box.appendChild(row);
  }
}

async function zcodeImport() {
  const models = pickedModels($("#zc-models"));
  if (!models.length) return toast("请至少勾选一个模型", true);
  const btn = $("#zc-import");
  btn.disabled = true; btn.textContent = "导入中…";
  const r = await api("/api/zcode/import", { providerId: $("#zc-provider").value, models });
  btn.disabled = false; btn.textContent = "一键导入到 ZCode";
  if (r.ok) {
    toast(`已导入 ${r.imported.length} 个模型到「${r.name}」，重启 ZCode 生效`);
    loadZcode();
  } else toast(r.error || "导入失败", true);
}

/* ---------------- TRAE Work CN 模块 ---------------- */
function renderTrae() {
  const t = (state.targets || {}).trae || {};
  $("#t-status").textContent = !t.installed
    ? "TRAE：未检测到" : (t.running ? "TRAE：正在运行" : "TRAE：已安装，可以辅助导入");
  providerSel = $("#t-provider");
  fillProviderSelect($("#t-provider"));
  $("#t-prepare").disabled = !t.installed;
}

async function traePrepare() {
  const btn = $("#t-prepare");
  btn.disabled = true; btn.textContent = "复制中…";
  const r = await api("/api/trae/prepare2", { providerId: $("#t-provider").value });
  btn.disabled = false; btn.textContent = "复制模型信息并启动 TRAE";
  if (r.ok) {
    $("#t-copied").textContent = "✓ 信息已复制到剪贴板，TRAE 正在启动…";
    toast("模型信息已复制到剪贴板，TRAE 正在启动");
  } else toast(r.error || "操作失败", true);
}

async function loadTraeModels() {
  const box = $("#t-list");
  box.innerHTML = '<span class="muted">加载中…</span>';
  const r = await api("/api/trae/models");
  if (!r.ok) { box.innerHTML = `<span class="muted">${esc(r.error || "读取失败")}</span>`; return; }
  if (!r.models.length) { box.innerHTML = '<span class="muted">TRAE 中暂无自定义模型（按上方步骤辅助导入后出现在这里）</span>'; return; }
  box.innerHTML = "";
  for (const m of r.models) {
    const row = document.createElement("div");
    row.className = "q-item";
    row.innerHTML = `
      <div class="grow">
        <div class="q-name">${esc(m.name)}
          ${m.status ? '<span class="badge badge-ok">已启用</span>' : '<span class="badge gray">已停用</span>'}</div>
        <div class="q-url mono">${esc(m.baseUrl || "-")}${m.vision ? " · 视觉" : ""}</div>
      </div>
      <button class="btn tiny ghost" data-act="tg">${m.status ? "停用" : "启用"}</button>
      <button class="btn danger tiny" data-act="del">删除</button>`;
    row.querySelector('[data-act="tg"]').onclick = async () => {
      const res = await api("/api/trae/models/toggle", { id: m.id, status: !m.status });
      if (res.ok) { toast("已切换（重启 TRAE 生效）"); loadTraeModels(); }
      else toast(res.error || "操作失败", true);
    };
    row.querySelector('[data-act="del"]').onclick = async () => {
      if (!(await confirmDlg(`从 TRAE 删除自定义模型「${m.name}」？`))) return;
      const res = await api("/api/trae/models/delete", { id: m.id });
      if (res.ok) { toast("已删除（重启 TRAE 生效）"); loadTraeModels(); }
      else toast(res.error || "删除失败", true);
    };
    box.appendChild(row);
  }
}

/* ---------------- Codex 页（只读展示 + 切换） ---------------- */
function render() {
  renderSidebar();
  renderDetail();
}

function renderSidebar() {
  const box = $("#provider-list");
  if (!box) return;
  box.innerHTML = "";
  for (const p of state.providers) {
    const card = document.createElement("div");
    card.className = "p-card" + (p.id === selected ? " selected" : "");
    const isActive = p.id === state.active;
    card.innerHTML = `
      <div class="p-name"><span>${esc(p.name)}</span>${isActive ? '<span class="badge badge-ok">使用中</span>' : ""}</div>
      <div class="p-url mono">${p.id === "original" ? "ChatGPT 官方账号，原始配置" : esc(p.base_url)}</div>`;
    card.onclick = () => { selected = p.id; renderSidebar(); renderDetail(); };
    box.appendChild(card);
  }
  $("#status-line").innerHTML =
    `<span class="dot ${state.codex_running ? "on" : "off"}"></span>` +
    `Codex ${state.codex_running ? "运行中" : "未运行"} · 当前：<b>${esc(activeName())}</b>`;
}

function activeName() {
  const p = state.providers.find((x) => x.id === state.active);
  if (!p) return state.active || "未知";
  return p.name;
}

/* ---------------- 详情区（只读，编辑入口在目标管理） ---------------- */
function renderDetail() {
  const d = $("#detail");
  const p = state.providers.find((x) => x.id === selected);
  if (!p) { d.innerHTML = ""; return; }
  const isActive = p.id === state.active;
  const rows = [];
  const fr = (k, v, wide) => rows.push(
    `<div class="f-row${wide ? " wide" : ""}"><span class="k">${k}</span><span class="v${/^(https?|~|\/|C:)/.test(String(v)) ? " mono" : ""}">${v}</span></div>`);

  if (p.id === "original") {
    fr("说明", `将 ${esc(state.config_file || "~/.codex/config.toml")} 还原为备份的原始内容（保留插件、MCP 等设置）`, true);
    fr("API Key", "不需要（使用官方登录凭据）");
  } else {
    fr("Base URL", esc(p.base_url));
    fr("API 格式", p.wire_api === "chat" ? "Chat Completions (/v1/chat/completions)" : "Responses（原生 /responses）");
    fr("鉴权方式", p.auth_mode === "authjson" ? "auth.json（CC Switch 同款）" : "环境变量");
    fr("API Key", esc(maskKey(p.api_key)));
    if (p.env_key && p.auth_mode !== "authjson") fr("环境变量", esc(p.env_key));
    fr("默认模型", `${esc(p.model || "-")}${!p.model && (p.models || []).length ? "（取映射第一行）" : ""}`);
    fr("推理力度", esc(p.reasoning_effort || "跟随模型目录默认"));
    fr("上下文 / 输出", `${p.context_window} / ${p.max_output_tokens} tokens`);
    fr("Review 模型", esc(p.review_model || "-"));
    fr("模型列表", (p.models || []).map((m) => `<span class="chip mono">${esc(m)}</span>`).join("") || "-", true);
  }
  d.innerHTML = `
    <div class="d-head"><h2>${esc(p.name)}</h2>${isActive ? '<span class="badge badge-ok">使用中</span>' : ""}
      <span class="badge gray" style="margin-left:auto">只读 · 在目标管理编辑</span></div>
    <div class="d-tag">${p.id === "original" ? "恢复 Codex 原始配置，通过 ChatGPT 官方账号登录使用。" : "自定义 API 供应商 · 所有目标页签共用"}</div>
    <div class="fields">${rows.join("")}</div>
    <div class="d-actions">
      <button class="btn big ${isActive ? "active" : "primary"}" id="btn-switch" ${isActive ? "disabled" : ""}
        style="width:auto;padding:11px 26px">
        ${isActive ? "✓ 当前正在使用" : "启用此配置"}</button>
    </div>`;
  $("#btn-switch") && ($("#btn-switch").onclick = doSwitch);
}

function maskKey(k) { return k && k.length > 12 ? k.slice(0, 8) + "••••••••" + k.slice(-4) : (k || "-"); }

async function doSwitch() {
  const btn = $("#btn-switch");
  btn.disabled = true; btn.textContent = "切换中…";
  const r = await api("/api/switch", { id: selected });
  if (r.ok) {
    await refresh(true);
    toast(`已切换到「${activeName()}」，重启 Codex 后生效`);
  } else {
    toast(r.error || "切换失败", true);
    await refresh(true);
  }
}

async function doDelete(p) {
  if (!(await confirmDlg(`确定删除供应商「${p.name}」吗？`))) return;
  const r = await api("/api/provider/delete", { id: p.id });
  if (r.ok) { toast("已删除"); await refresh(); }
  else toast(r.error || "删除失败", true);
}

/* ---------------- 弹窗（添加/编辑供应商，入口在目标管理） ---------------- */
function openModal(p) {
  editingId = p ? p.id : null;
  $("#modal-title").textContent = p ? "编辑供应商" : "添加供应商";
  $("#f-name").value = p ? p.name : "";
  $("#f-base").value = p ? p.base_url : "";
  $("#f-wire").value = p ? (p.wire_api || "responses") : "responses";
  $("#f-authmode").value = p ? (p.auth_mode || "env") : "authjson";
  $("#f-effort").value = p ? (p.reasoning_effort || "") : "";
  $("#f-key").value = "";
  $("#f-key").type = "password";
  $("#f-key").placeholder = p && p.api_key ? "已保存：" + maskKey(p.api_key) + "（留空则不修改）" : "sk-...";
  $("#f-env").value = p && p.env_key ? p.env_key : "";
  $("#f-ctx").value = p ? p.context_window : 200000;
  $("#f-max").value = p ? p.max_output_tokens : 32768;
  limitAuto = true;
  $("#f-limits-hint").textContent = "";
  $("#f-limits-hint").style.cssText = "";
  draftModels = (p && p.models || []).map((m) => ({ id: m, on: true }));
  $("#f-model-input").value = "";
  renderModelChips();
  $("#test-result").className = "hidden";
  $("#modal-mask").classList.remove("hidden");
  syncAuthMode();
  if (!p) $("#f-name").focus();
}

function syncAuthMode() {
  // auth.json 模式不需要环境变量名
  $("#f-env-wrap").style.display = $("#f-authmode").value === "env" ? "" : "none";
}

function closeModal() { $("#modal-mask").classList.add("hidden"); }

function renderModelChips() {
  const box = $("#model-list");
  box.innerHTML = "";
  if (!draftModels.length) {
    box.innerHTML = '<span class="muted">尚未获取模型，可点击右上角按钮拉取，或手动输入添加</span>';
  }
  for (const m of draftModels) {
    const chip = document.createElement("span");
    chip.className = "model-chip" + (m.on ? " on" : "");
    chip.innerHTML = `${esc(m.id)}<span class="x">✕</span>`;
    chip.title = m.on ? "已选入目录，点击取消选入" : "未选入目录，点击选入";
    chip.onclick = (e) => {
      if (e.target.classList.contains("x")) {
        draftModels = draftModels.filter((x) => x !== m);
      } else {
        m.on = !m.on;
      }
      renderModelChips();
    };
    box.appendChild(chip);
  }
  // 默认/review 模型下拉 = 选中的模型
  const on = draftModels.filter((m) => m.on).map((m) => m.id);
  fillSelect($("#f-model"), on, on[0] || "");
  fillSelect($("#f-review"), ["(无)", ...on], "(无)");
  if (limitAuto) detectLimits($("#f-model").value);
}

function fillSelect(sel, items, cur) {
  sel.innerHTML = "";
  for (const it of items) {
    const o = document.createElement("option");
    o.value = it; o.textContent = it;
    sel.appendChild(o);
  }
  if (cur) sel.value = cur;
}

function collectProvider() {
  const keyInput = $("#f-key").value.trim();
  const p = {
    id: editingId || undefined,
    name: $("#f-name").value.trim(),
    base_url: $("#f-base").value.trim(),
    wire_api: $("#f-wire").value,
    auth_mode: $("#f-authmode").value,
    api_key: keyInput,             // 空则后端用旧值补（仅编辑时）
    env_key: $("#f-env").value.trim(),
    reasoning_effort: $("#f-effort").value,
    models: draftModels.filter((m) => m.on).map((m) => m.id),
    model: $("#f-model").value === "(无)" ? "" : $("#f-model").value,
    review_model: $("#f-review").value === "(无)" ? "" : $("#f-review").value,
    context_window: +$("#f-ctx").value || 200000,
    max_output_tokens: +$("#f-max").value || 32768,
  };
  return p;
}

async function saveProvider() {
  const p = collectProvider();
  if (!p.name) return toast("请填写名称", true);
  if (!p.base_url) return toast("请填写 Base URL", true);
  if (p.auth_mode === "env" && !p.env_key) p.env_key = autoEnv(p.name);
  const r = await api("/api/provider", { provider: p });
  if (r.ok) {
    closeModal();
    selected = r.id;
    await refresh(true);
    if (editingId) toast("已保存");
    else toast("供应商已保存到供应商库 —— Codex / Qoder / ZCode / TRAE 等页已自动识别");
  } else toast(r.error || "保存失败", true);
}

function autoEnv(name) {
  let s = name.replace(/[^A-Za-z0-9]+/g, "_").toUpperCase().replace(/^_+|_+$/g, "");
  if (!s || /^[0-9]/.test(s)) s = "CODEX_" + (s || "API");
  return s + "_API_KEY";
}

/* ---------------- 测试 / 拉取模型 ---------------- */
async function testConn() {
  const p = collectProvider();
  const box = $("#test-result");
  box.className = ""; box.style.display = "";
  box.classList.remove("ok", "err");
  box.textContent = "测试中…";
  const r = await api("/api/test", { provider: p });
  if (r.ok !== undefined && r.ok) {
    box.className = "ok";
    box.textContent = `✓ 连接成功（${r.ms}ms，模型 ${r.model}）：${r.reply}`;
  } else {
    box.className = "err";
    box.textContent = "✗ " + (r.error || "连接失败");
  }
}

async function fetchModels() {
  const p = collectProvider();
  const btn = $("#btn-fetch");
  btn.disabled = true; btn.textContent = "拉取中…";
  const r = await api("/api/models", { provider: p });
  btn.disabled = false; btn.textContent = "⟳ 获取模型列表";
  if (r.ok) {
    const known = new Set(draftModels.map((m) => m.id));
    for (const id of r.models) {
      if (!known.has(id)) draftModels.push({ id, on: draftModels.length === 0 });
    }
    if (!draftModels.some((m) => m.on) && draftModels.length) draftModels[0].on = true;
    renderModelChips();
    toast(`获取到 ${r.models.length} 个模型`);
  } else toast(r.error || "拉取失败", true);
}

function addManualModel() {
  const inp = $("#f-model-input");
  const id = inp.value.trim();
  if (!id) return;
  if (draftModels.some((m) => m.id === id)) return toast("模型已存在", true);
  draftModels.push({ id, on: true });
  inp.value = "";
  renderModelChips();
}

/* ---------------- 重启 Codex ---------------- */
async function restartCodex() {
  if (state.codex_running && !(await confirmDlg("Codex 正在运行，确认关闭并重启吗？"))) return;
  const btn = $("#btn-restart");
  if (btn) btn.disabled = true;
  const r = await api("/api/restart-codex", {});
  if (btn) btn.disabled = false;
  if (r.ok) toast("Codex 正在启动…");
  else toast(r.error || "重启失败", true);
  setTimeout(refresh, 4000);
}

/* ---------------- utils ---------------- */
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* 自定义确认框（替代原生 confirm，桌面窗口下可靠） */
function confirmDlg(msg) {
  return new Promise((resolve) => {
    const mask = $("#confirm-mask");
    $("#confirm-msg").textContent = msg;
    mask.classList.remove("hidden");
    const done = (v) => {
      mask.classList.add("hidden");
      $("#confirm-yes").onclick = null;
      $("#confirm-no").onclick = null;
      resolve(v);
    };
    $("#confirm-yes").onclick = () => done(true);
    $("#confirm-no").onclick = () => done(false);
  });
}

/* ---------------- 供应商配置迁移 ---------------- */
async function exportConfiguration() {
  const btn = $("#btn-export-config");
  if (btn) { btn.disabled = true; btn.textContent = "导出中…"; }
  try {
    const payload = await api("/api/providers/export");
    if (!payload || !Array.isArray(payload.providers)) {
      throw new Error("后端返回的配置格式无效");
    }
    const text = JSON.stringify(payload, null, 2);
    const blob = new Blob([text], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const day = new Date().toISOString().slice(0, 10);
    a.href = url;
    a.download = `api-switch-config-${day}.json`;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast(`已导出 ${payload.providers.length} 个供应商（文件包含 API Key，请妥善保管）`);
  } catch (e) {
    toast("导出失败：" + (e && e.message || e), true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "导出配置"; }
  }
}

async function importConfigurationFile(file) {
  if (!file) return;
  const btn = $("#btn-import-config");
  try {
    let payload;
    try {
      payload = JSON.parse(await file.text());
    } catch (e) {
      throw new Error("文件不是有效的 JSON");
    }
    if (!payload || !Array.isArray(payload.providers)) {
      throw new Error("文件中没有有效的供应商列表");
    }
    const count = payload.providers.length;
    if (!count) {
      throw new Error("文件中的供应商列表为空");
    }
    if (!(await confirmDlg(
      `将导入 ${count} 个供应商；同 ID 或同名称与 Base URL 的配置会更新现有条目。\n` +
      "导入文件可能包含 API Key，确认继续吗？"))) return;
    if (btn) { btn.disabled = true; btn.textContent = "导入中…"; }
    const r = await api("/api/providers/import", payload);
    if (!r.ok) {
      toast(r.error || "导入失败", true);
      return;
    }
    await refresh(true);
    toast(`导入完成：新增 ${r.added || 0} 个，更新 ${r.updated || 0} 个`);
  } catch (e) {
    toast("导入失败：" + (e && e.message || e), true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "导入配置"; }
    const inp = $("#config-file-input");
    if (inp) inp.value = "";
  }
}

/* ---------------- init ---------------- */
$("#btn-add").onclick = () => openModal(null);
$("#btn-add-lib").onclick = () => openModal(null);
$("#btn-goto-providers").onclick = () => switchTab("targets");
$("#modal-close").onclick = closeModal;
$("#btn-cancel").onclick = closeModal;
$("#modal-mask").onclick = (e) => { if (e.target.id === "modal-mask") closeModal(); };
$("#btn-save").onclick = saveProvider;
$("#btn-test").onclick = testConn;
$("#btn-fetch").onclick = fetchModels;
$("#btn-add-model").onclick = addManualModel;
$("#f-model-input").addEventListener("keydown", (e) => { if (e.key === "Enter") addManualModel(); });
$("#key-eye").onclick = () => {
  const k = $("#f-key");
  k.type = k.type === "password" ? "text" : "password";
};
$("#btn-restart").onclick = restartCodex;
$("#btn-import-config").onclick = () => $("#config-file-input").click();
$("#config-file-input").onchange = (e) => importConfigurationFile(e.target.files[0]);
$("#btn-export-config").onclick = exportConfiguration;
$("#f-authmode").addEventListener("change", syncAuthMode);
$("#f-model").addEventListener("change", () => { limitAuto = true; detectLimits($("#f-model").value); });
["f-ctx", "f-max"].forEach((id) => $("#" + id).addEventListener("input", () => {
  limitAuto = false;
  const h = $("#f-limits-hint");
  h.textContent = "已手动修改，切换模型可重新自动识别";
  h.style.borderColor = "var(--line)";
  h.style.background = "var(--field)";
  h.style.color = "var(--muted)";
}));
$("#q2-provider").addEventListener("change", renderQoder2);
$("#q2-import").onclick = qoder2Import;
$("#qn-provider").addEventListener("change", renderQnModels);
$("#qn-import").onclick = qodercnImport;
$("#zc-provider").addEventListener("change", renderZcode);
$("#zc-import").onclick = zcodeImport;
$("#t-provider").addEventListener("change", () => { providerSel = $("#t-provider"); });
$("#t-prepare").onclick = traePrepare;
$("#legacy-yes").onclick = () => resolveLegacy(true);
$("#legacy-no").onclick = () => resolveLegacy(false);

/* ---------------- 网络设置 ---------------- */
function openNet() {
  $("#f-proxy").value = (state.settings && state.settings.proxy) || "";
  $("#net-mask").classList.remove("hidden");
}
function closeNet() { $("#net-mask").classList.add("hidden"); }
$("#btn-net").onclick = openNet;
$("#btn-refresh").onclick = async () => {
  const b = $("#btn-refresh");
  b.disabled = true; b.textContent = "⟳ 刷新中…";
  try {
    await refresh(true);
    toast("已刷新");
  } catch (e) {
    toast("刷新失败：" + (e && e.message || e), true);
  } finally {
    b.disabled = false; b.textContent = "⟳ 刷新";
  }
};
$("#net-close").onclick = closeNet;
$("#net-cancel").onclick = closeNet;
$("#net-mask").onclick = (e) => { if (e.target.id === "net-mask") closeNet(); };
$("#net-save").onclick = async () => {
  const r = await api("/api/settings", { proxy: $("#f-proxy").value.trim() });
  if (r.ok) { toast("网络设置已保存"); closeNet(); await refresh(true); }
  else toast(r.error || "保存失败", true);
};
$("#btn-uninstall").onclick = async () => {
  closeNet();
  const msg = "将执行以下操作，且不可恢复：\n\n" +
    "1. 还原 Codex 原始配置（用首次修改前的备份覆盖回 config.toml / auth.json）\n" +
    "2. 删除本工具全部数据：供应商库与其中保存的 API Key\n\n" +
    "已导入到 Qoder / ZCode / TRAE 的模型不受影响，需在各软件内自行删除。\n" +
    "确认清除后，请手动删除本程序的 exe 文件完成卸载。是否继续？";
  if (!(await confirmDlg(msg))) return;
  const r = await api("/api/uninstall", { restoreOriginal: true });
  if (!r.ok) { toast("清除失败：" + (r.errors || []).join("；"), true); return; }
  toast(r.restored ? "已还原 Codex 原始配置并清除工具数据" : "已清除工具数据", false);
  document.body.innerHTML = '<div style="font:14px/1.9 sans-serif;padding:56px;color:#334;max-width:560px;margin:80px auto">' +
    '<h2 style="margin:0 0 12px">数据已清除</h2>' +
    '<p>' + (r.restored ? "Codex 原始配置已还原。<br>" : "") +
    '本工具的全部数据（供应商库与 Key）已删除。<br><br>' +
    '最后一步：<b>关闭本窗口，然后删除本程序的 exe 文件</b>，即完成卸载。</p></div>';
  setTimeout(() => { try { window.close(); } catch (e) {} setTimeout(() => location.reload, 1500); }, 4000);
};
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeModal(); closeNet(); } });

/* ---------------- 极光 3D 氛围层（零依赖 Canvas 伪 3D：粒子场 + 线框多面体 + 鼠标视差） ---------------- */
(function aurora3D() {
  const cv = document.getElementById('bg3d');
  if (!cv || !cv.getContext) return;
  if (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const ctx = cv.getContext('2d');
  let W = 0, H = 0, DPR = 1;
  function resize() {
    DPR = Math.min(devicePixelRatio || 1, 1.5);
    W = innerWidth; H = innerHeight;
    cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR);
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }
  addEventListener('resize', resize); resize();

  const F = 14;                        // 相机焦距（透视强度与原型 three.js 场景一致）
  let mx = 0, my = 0;                  // 鼠标视差 [-.5,.5]
  addEventListener('mousemove', (e) => { mx = e.clientX / W - .5; my = e.clientY / H - .5; });

  /* 粒子场：球壳分布，渲染为小方块（同原型 Points 形态） */
  const pts = [];
  for (let i = 0; i < 220; i++) {
    const r = 6 + Math.random() * 11, th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
    pts.push([r * Math.sin(ph) * Math.cos(th), r * Math.sin(ph) * Math.sin(th) * .6, r * Math.cos(ph) * .5]);
  }
  /* 线框几何：二十面体（大，右下）+ 八面体（小，左上） */
  function icosahedron(R) {
    const t = (1 + Math.sqrt(5)) / 2, v = [];
    for (const a of [-1, 1]) for (const b of [-1, 1]) v.push([0, a, b * t], [a, b * t, 0], [a * t, 0, b]);
    const n = Math.hypot(0, 1, t);
    const verts = v.map((p) => p.map((c) => c / n * R));
    let min = 1e9;
    for (let i = 0; i < verts.length; i++) for (let j = i + 1; j < verts.length; j++)
      min = Math.min(min, Math.hypot(verts[i][0] - verts[j][0], verts[i][1] - verts[j][1], verts[i][2] - verts[j][2]));
    const e = [];
    for (let i = 0; i < verts.length; i++) for (let j = i + 1; j < verts.length; j++)
      if (Math.hypot(verts[i][0] - verts[j][0], verts[i][1] - verts[j][1], verts[i][2] - verts[j][2]) < min * 1.05) e.push([i, j]);
    return { verts, e };
  }
  function octahedron(R) {
    const verts = [[R, 0, 0], [-R, 0, 0], [0, R, 0], [0, -R, 0], [0, 0, R], [0, 0, -R]];
    const e = [];
    for (let i = 0; i < 6; i++) for (let j = i + 1; j < 6; j++)
      if (!(i % 2 === 0 && j === i + 1)) e.push([i, j]);   // 跳过对径点对
    return { verts, e };
  }
  const ico = icosahedron(3.4), oct = octahedron(1.7);

  function rot(p, ax, ay) {            // 先绕 Y 再绕 X
    let [x, y, z] = p;
    let c = Math.cos(ay), s = Math.sin(ay);
    [x, z] = [x * c + z * s, -x * s + z * c];
    c = Math.cos(ax); s = Math.sin(ax);
    [y, z] = [y * c - z * s, y * s + z * c];
    return [x, y, z];
  }
  function project(p, off) {
    const d = F + p[2] + off[2];
    if (d < 1.2) return null;
    const k = F / d * Math.min(W, H) / 16;
    return [W / 2 + (p[0] + off[0] + mx * 2.4) * k, H / 2 - (p[1] + off[1] - my * 1.6) * k, d, k];
  }

  let hidden = false;
  document.addEventListener('visibilitychange', () => { hidden = document.hidden; });
  function wire(shape, off, ax, ay, color) {
    const vs = shape.verts.map((v) => project(rot(v, ax, ay), off));
    ctx.strokeStyle = color; ctx.lineWidth = 1;
    ctx.beginPath();
    for (const [i, j] of shape.e) {
      const a = vs[i], b = vs[j];
      if (!a || !b) continue;
      ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]);
    }
    ctx.stroke();
  }
  function frame(t) {
    requestAnimationFrame(frame);
    if (hidden || !W) return;
    ctx.clearRect(0, 0, W, H);
    const ry = t * .00006 + mx * .25, rx = my * .12;
    for (const p of pts) {
      const pr = project(rot(p, rx, ry), [0, 0, 0]);
      if (!pr) continue;
      ctx.fillStyle = `rgba(99,102,241,${Math.min(.5, Math.max(.07, 4.9 / pr[2])).toFixed(3)})`;
      const size = Math.max(1, .08 * pr[3]);
      ctx.fillRect(pr[0], pr[1], size, size);
    }
    wire(ico, [8, -3.5, -5], t * .00005, t * .00008, 'rgba(79,70,229,.14)');
    wire(oct, [-8.5, 3.5, -4], t * .00006, -t * .0001, 'rgba(8,145,178,.2)');
  }
  requestAnimationFrame(frame);
})();

refresh();
loadModelLimitsOnline();
