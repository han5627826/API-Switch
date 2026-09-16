/* 前端逻辑 —— 所有目标页共用供应商库 */
"use strict";

let state = { providers: [], active: null, codex_running: false,
              targets: {}, qoder_imports: [], trae_imports: [] };
let selected = null;          // 当前详情页展示的供应商 id
let editingId = null;         // 弹窗正在编辑的 id（null=新增）
let draftModels = [];         // 弹窗内模型集合（对象 {id, on}）
const $ = (s) => document.querySelector(s);

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
  const hit = lookupLimit(modelId);
  if (hit) {
    $("#f-ctx").value = hit.ctx;
    $("#f-max").value = hit.out || 32768;
    if (hint) hint.textContent =
      `✓ 已自动识别「${modelId}」支持上限：上下文 ${hit.ctx} / 输出 ${hit.out || "?"}（${hit.src}规格表，可手动修改）`;
  } else if (hint) {
    hint.textContent = `未收录「${modelId}」的公开规格，保留当前值，可手动修改`;
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
  render();
  renderQoder2();
  renderQodercn(false);
  renderZcode();
  renderTrae();
  renderTargets();
}

/* ---------------- 顶部模块 Tab ---------------- */
document.querySelectorAll("#tabs .tab").forEach((btn) => {
  btn.onclick = () => switchTab(btn.dataset.view);
});
function switchTab(view) {
  document.querySelectorAll("#tabs .tab").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === view);
  });
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  $("#view-" + view).classList.remove("hidden");
  if (view === "qoder2") loadQoder2List();
  if (view === "qodercn") loadQodercn();
  if (view === "zcode") loadZcode();
  if (view === "trae") loadTraeModels();
  if (view === "targets") renderTargets();
}

/* ---------------- 导入目标管理 ---------------- */
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

function renderTargets() {
  const grid = $("#targets-grid");
  if (!grid) return;
  const t = state.targets || {};
  grid.innerHTML = "";
  for (const def of TARGET_DEFS) {
    const info = t[def.key] || {};
    const inst = !!info.installed;
    const card = document.createElement("div");
    card.className = "t-card" + (inst ? "" : " off");
    card.innerHTML = `
      <div class="t-head"><b>${esc(def.name)}</b>
        <span class="badge ${inst ? "" : "gray"}">${inst ? (info.running ? "运行中" : "已检测到") : "未检测到"}</span></div>
      <div class="t-desc">${esc(def.desc)}</div>
      <div class="t-hint">用法：${esc(def.how)}</div>
      <button class="btn tiny ${inst ? "primary" : "ghost"}" ${inst ? "" : "disabled"}>前往导入 →</button>`;
    card.querySelector("button").onclick = () => {
      switchTab(def.tab);
      document.querySelector(`#tabs .tab[data-view="${def.tab}"]`).scrollIntoView();
    };
    grid.appendChild(card);
  }
}

/* ---------------- 供应商下拉 + 模型勾选（公用） ---------------- */
function fillProviderSelect(sel) {
  const cur = sel.value;
  sel.innerHTML = "";
  for (const p of state.providers.filter((x) => x.id !== "original")) {
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
  if (!models.length) { box.innerHTML = '<span class="muted">该供应商暂无模型，请先在 Codex 页获取模型</span>'; return; }
  for (const id of models) {
    const meta = modelMeta(id);
    const item = document.createElement("label");
    item.className = "model-check on";
    item.dataset.mid = id;
    item.innerHTML = `<input type="checkbox" checked> ${esc(id)} ` +
      `<span class="muted">${meta.contextWindow}/${meta.maxOutputTokens}${meta.reasoning ? " · 推理" : ""}${meta.vision ? " · 视觉" : ""}</span>`;
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
  if (statusEl) statusEl.textContent = !installed
    ? "未检测到目标软件" : (running ? "⚠ 目标正在运行，建议先完全退出再导入" : "已就绪，可以导入");
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
        <div class="q-url">${esc(p.baseUrl || "-")} · ${esc(p.protocol || "openai")} · ${esc(p.type || "")}</div>
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
        <div class="q-url">${esc(p.baseUrl || "-")} · ${esc(p.protocol || "openai")} · ${esc(p.type || "")}</div>
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
          ${p.enabled ? '<span class="badge">使用中</span>' : ""}
          ${p.managed ? '<span class="badge gray">由本工具导入</span>' : ""}</div>
        <div class="q-url">${esc(p.baseUrl || "-")} · ${esc(p.kind || "")}${p.hasKey ? "" : " · 未保存 Key"}</div>
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
    ? "未检测到 TRAE Work CN（TRAE SOLO CN）" : (t.running ? "TRAE 正在运行" : "已安装，可以辅助导入");
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
          ${m.status ? '<span class="badge">已启用</span>' : '<span class="badge gray">已停用</span>'}</div>
        <div class="q-url">${esc(m.baseUrl || "-")}${m.vision ? " · 视觉" : ""}</div>
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

/* ---------------- Codex 侧边栏 ---------------- */
function render() {
  renderSidebar();
  renderDetail();
}

function renderSidebar() {
  const box = $("#provider-list");
  box.innerHTML = "";
  for (const p of state.providers) {
    const card = document.createElement("div");
    card.className = "p-card" + (p.id === selected ? " selected" : "");
    const isActive = p.id === state.active;
    card.innerHTML = `
      <div class="p-name"><span>${esc(p.name)}</span>${isActive ? '<span class="badge">使用中</span>' : ""}</div>
      <div class="p-url">${p.id === "original" ? "ChatGPT 官方账号，原始配置" : esc(p.base_url)}</div>`;
    card.onclick = () => { selected = p.id; render(); };
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

/* ---------------- 详情区 ---------------- */
function renderDetail() {
  const d = $("#detail");
  const p = state.providers.find((x) => x.id === selected);
  if (!p) { d.innerHTML = ""; return; }
  const isActive = p.id === state.active;

  if (p.id === "original") {
    d.innerHTML = `
      <div class="d-card">
        <div class="d-head"><h2>${esc(p.name)}</h2>${isActive ? '<span class="badge">使用中</span>' : ""}</div>
        <div class="d-tag">恢复 Codex 原始配置，通过 ChatGPT 官方账号登录使用。</div>
        <div class="field"><div class="k">说明</div><div class="v">将 ${esc(state.config_file)} 还原为备份的原始内容（保留插件、MCP 等设置）。</div></div>
        <div class="field"><div class="k">API Key</div><div class="v">不需要（使用官方登录凭据）</div></div>
        <div class="d-actions">
          <button class="btn big ${isActive ? "active" : "primary"}" id="btn-switch" ${isActive ? "disabled" : ""}>
            ${isActive ? "✓ 当前正在使用" : "启用此配置"}</button>
        </div>
      </div>`;
  } else {
    d.innerHTML = `
      <div class="d-card">
        <div class="d-head"><h2>${esc(p.name)}</h2>${isActive ? '<span class="badge">使用中</span>' : ""}</div>
        <div class="d-tag">自定义 API 供应商 · 所有目标页签共用</div>
        <div class="field"><div class="k">Base URL</div><div class="v">${esc(p.base_url)}</div></div>
        <div class="field"><div class="k">API 格式</div><div class="v">${p.wire_api === "chat" ? "Chat Completions (/v1/chat/completions)" : "Responses（原生 /responses）"}</div></div>
        <div class="field"><div class="k">鉴权方式</div><div class="v">${p.auth_mode === "authjson" ? "auth.json（CC Switch 同款）" : "环境变量"}</div></div>
        <div class="field"><div class="k">API Key</div><div class="v">${esc(maskKey(p.api_key))}</div></div>
        ${p.env_key && p.auth_mode !== "authjson" ? `<div class="field"><div class="k">环境变量</div><div class="v">${esc(p.env_key)}</div></div>` : ""}
        <div class="field"><div class="k">默认模型</div><div class="v">${esc(p.model || "-")}${!p.model && (p.models || []).length ? "（取映射第一行）" : ""}</div></div>
        <div class="field"><div class="k">推理力度</div><div class="v">${esc(p.reasoning_effort || "跟随模型目录默认")}</div></div>
        <div class="field"><div class="k">Review 模型</div><div class="v">${esc(p.review_model || "-")}</div></div>
        <div class="field"><div class="k">模型列表</div><div class="v">${(p.models || []).map(esc).join("、") || "-"}</div></div>
        <div class="field"><div class="k">上下文 / 输出</div><div class="v">${p.context_window} / ${p.max_output_tokens} tokens</div></div>
        <div class="d-actions">
          <button class="btn big ${isActive ? "active" : "primary"}" id="btn-switch" ${isActive ? "disabled" : ""}>
            ${isActive ? "✓ 当前正在使用" : "启用此配置"}</button>
          <button class="btn ghost big" id="btn-edit">编辑</button>
          <button class="btn danger big" id="btn-del">删除</button>
        </div>
      </div>`;
  }
  $("#btn-switch") && ($("#btn-switch").onclick = doSwitch);
  $("#btn-edit") && ($("#btn-edit").onclick = () => openModal(p));
  $("#btn-del") && ($("#btn-del").onclick = () => doDelete(p));
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

/* ---------------- 弹窗 ---------------- */
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
    else toast("供应商已保存 —— 切到上方 Qoder / ZCode / TRAE Work CN 等页签即可一键导入（详见「目标管理」）");
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
  btn.disabled = true;
  const r = await api("/api/restart-codex", {});
  btn.disabled = false;
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

/* ---------------- init ---------------- */
$("#btn-add").onclick = () => openModal(null);
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
$("#f-authmode").addEventListener("change", syncAuthMode);
$("#f-model").addEventListener("change", () => { limitAuto = true; detectLimits($("#f-model").value); });
["f-ctx", "f-max"].forEach((id) => $("#" + id).addEventListener("input", () => {
  limitAuto = false;
  $("#f-limits-hint").textContent = "已手动修改，切换模型可重新自动识别";
}));
$("#q2-provider").addEventListener("change", renderQoder2);
$("#q2-import").onclick = qoder2Import;
$("#qn-provider").addEventListener("change", renderQnModels);
$("#qn-import").onclick = qodercnImport;
$("#zc-provider").addEventListener("change", renderZcode);
$("#zc-import").onclick = zcodeImport;
$("#t-provider").addEventListener("change", () => { providerSel = $("#t-provider"); });
$("#t-prepare").onclick = traePrepare;

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
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

refresh();
loadModelLimitsOnline();
