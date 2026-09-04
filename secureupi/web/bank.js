/* SecureUPI — PSP Operations Console client.
 *
 * Shows the BANK/PSP side of every payment the demo phone produces:
 *   live feed → SecureUPI risk rounds → PSP decision → NPCI/UPI settlement.
 * Plus an operator risk-policy tuner with a validation replay.
 */
"use strict";

const $ = (id) => document.getElementById(id);
const pad2 = (n) => String(n).padStart(2, "0");
const inr = (n) => "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 });
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const SIG_LABELS = {
  amount_fill_s: "Amount entry time", amount_corrections: "Amount corrections",
  amount_max_pause_s: "Longest typing pause", pay_dwell_s: "Review before Pay",
  pin_cps: "PIN entry speed", pin_max_pause_s: "Longest PIN pause",
  pin_resets: "PIN re-entries", pin_hold_std_ms: "Tap-hold variability",
  pin_tap_offset_px: "Tap accuracy offset",
};
const SIG_UNITS = { amount_fill_s: "s", amount_max_pause_s: "s", pay_dwell_s: "s",
                    pin_cps: "d/s", pin_max_pause_s: "s", pin_hold_std_ms: "ms",
                    pin_tap_offset_px: "px" };

const DEFAULT_POLICY = { low_max: 30, medium_max: 65, challenge_block_at: 45, hard_gate_amount: 10000 };
const state = { tx: [], selected: null, seen: new Set(), policy: { ...DEFAULT_POLICY }, profiles: [] };
let exploreTimer = null;

/* ------------------------------- utils -------------------------------- */
function toast(text, ok = true) {
  const t = document.createElement("div");
  t.className = "toast-ok";
  if (!ok) t.style.background = "#2c0a0a";
  t.textContent = text;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

function fmtTime(iso) {
  if (!iso) return "";
  const ms = Date.parse(iso);
  if (isNaN(ms)) return iso.slice(11, 19);
  const d = new Date(ms);
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
}

const LVL_COLOR = { LOW: "#22c55e", MEDIUM: "#f59e0b", HIGH: "#ef4444" };
const ACT_CLS = { APPROVE: "p-approve", "STEP-UP": "p-stepup", BLOCK: "p-block" };
const ACT_TEXT = { APPROVE: "APPROVE", "STEP-UP": "STEP-UP", BLOCK: "BLOCK" };

function srcSpan(tx) {
  return tx.source === "sample"
    ? '<span class="src src-sample">SIMULATED</span>'
    : '<span class="src src-live">LIVE</span>';
}

function stateTag(tx) {
  const map = {
    approved: ["APPROVED", "p-approve"],
    step_up: ["STEP-UP · AWAITING", "p-stepup"],
    blocked: ["BLOCKED", "p-block"],
    fraud_reported: ["FRAUD REPORTED", "p-block"],
    overridden: ["OVERRIDDEN", "p-stepup"],
  };
  const [txt, cls] = map[tx.state] || [tx.state, "p-stepup"];
  return `<span class="pchip ${cls}">${txt}</span>`;
}

function outcomeChain(tx) {
  const chain = tx.rounds.map((r, i) =>
    `<span class="stepno">${i + 1}</span><span class="pchip ${ACT_CLS[r.action]}">${ACT_TEXT[r.action]}</span>`);
  return `<span class="path-chain">${chain.join('<span class="arrow">→</span>')}</span>`;
}

function settlementCell(tx) {
  const sw = tx.switch;
  if (!sw) return `<td class="score-cell" style="color:#54627d">—</td>`;
  if (sw.status === "settled") {
    const utr = sw.utr || "";
    return `<td class="score-cell"><span class="pchip p-approve">NPCI ✓</span>` +
      `<div class="utr">${esc(utr.slice(0, 4))}…${esc(utr.slice(-4))}</div></td>`;
  }
  if (sw.status === "not_reached") {
    return `<td class="score-cell" style="color:#54627d;font-size:10.5px">not sent<small style="color:#3f4c66">pre-auth block</small></td>`;
  }
  return `<td class="score-cell" style="color:#fbbf24;font-size:10.5px">in risk review</td>`;
}

/* -------------------------------- KPIs -------------------------------- */
function renderKpis() {
  const txs = state.tx;
  const live = txs.filter((t) => t.source === "live").length;
  const blocked = txs.filter((t) => ["blocked", "fraud_reported"].includes(t.state));
  const protectedAmt = blocked.reduce((a, t) => a + t.amount, 0);
  const overridden = txs.filter((t) => t.state === "overridden");
  const stepups = txs.filter((t) => t.rounds[0] && t.rounds[0].action === "STEP-UP");
  const cleared = stepups.filter((t) => ["approved", "overridden"].includes(t.state)).length;
  const reports = txs.filter((t) => t.report_id).length;
  const pending = txs.filter((t) => t.state === "blocked").length;
  const settled = txs.filter((t) => t.switch && t.switch.status === "settled");
  const settledAmt = settled.reduce((a, t) => a + t.amount, 0);

  const card = (cls, k, v, s) =>
    `<div class="kpi ${cls}"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`;
  $("kpis").innerHTML =
    card("", "Payments monitored", txs.length,
      `${live} live from demo · ${txs.length - live} simulated`) +
    card("bad", "Fraud attempts blocked", protectedAmt ? inr(protectedAmt) : "₹0",
      `${blocked.length} blocked${pending ? ` · <span style="color:#fca5a5">${pending} needs review</span>` : ""}`) +
    card("warn", "Step-ups issued", String(stepups.length),
      `${cleared}/${stepups.length || 0} cleared by re-authentication`) +
    card("info", "Settled via NPCI", String(settled.length),
      settledAmt ? `${inr(settledAmt)} cleared to beneficiaries` : "no approvals yet") +
    card("", "Fraud reports filed", String(reports),
      overridden.length ? `${overridden.length} override by PSP` : "on blocked payments");
}

/* ------------------------- per-customer strip ------------------------- */
function renderCustomers() {
  const box = $("custStrip");
  const byName = new Map();
  for (const tx of state.tx) {
    const name = tx.customer?.name || "?";
    if (!byName.has(name)) byName.set(name, { name, bank: tx.customer?.bank || "", live: false, n: 0, step: 0, blk: 0 });
    const g = byName.get(name);
    g.n += 1;
    if (tx.source === "live") g.live = true;
    if (tx.rounds[0] && tx.rounds[0].action === "STEP-UP") g.step += 1;
    if (["blocked", "fraud_reported"].includes(tx.state)) g.blk += 1;
  }
  const profMap = new Map(state.profiles.map((p) => [p.name, p]));
  const groups = [...byName.values()].sort((a, b) => b.n - a.n).slice(0, 7);
  if (!groups.length) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = groups.map((g) => {
    const prof = profMap.get(g.name);
    const stepPct = g.n ? Math.round((g.step / g.n) * 100) : 0;
    return `<div class="cust-card">
      <div class="cn">${esc(g.name)}<small>${g.live ? "LIVE" : "SIMULATED"} · ${esc(g.bank)}</small></div>
      <div class="row2"><span>${g.n} payments</span><span>step-ups <b>${stepPct}%</b></span>` +
      (g.blk ? `<span class="blk">${g.blk} blocked</span>` : "") +
      (prof ? `<span title="learned baseline sessions">baseline ${prof.n} sess</span>` : "") +
      `</div></div>`;
  }).join("");
}

/* ------------------------------- table -------------------------------- */
function opsCell(tx) {
  const src = srcSpan(tx);
  if (tx.state === "blocked") {
    return `<td class="ops">${src}` +
      `<button class="op-btn op-danger" data-tx="${tx.id}" data-act="confirm_fraud">Confirm fraud</button>` +
      `<button class="op-btn op-warn" data-tx="${tx.id}" data-act="override_approve">Override</button></td>`;
  }
  if (tx.state === "fraud_reported") {
    return `<td class="ops">${src}<span class="rep-tag">${esc(tx.report_id || "")}</span></td>`;
  }
  if (tx.state === "overridden") {
    return `<td class="ops">${src}<span class="rep-tag" style="color:#fde68a;border-color:#713f12;background:#2a1d05">PSP OVERRIDE</span></td>`;
  }
  return `<td class="ops">${src}</td>`;
}

function renderTable(freshIds) {
  const body = $("txBody");
  if (!state.tx.length) {
    body.innerHTML = `<tr><td colspan="9" class="tx-empty">No transactions yet — run a scenario on the <b>payment demo</b> page, or load a sample bank day.</td></tr>`;
    return;
  }
  body.innerHTML = "";
  for (const tx of state.tx) {
    const tr = document.createElement("tr");
    tr.className = "row" + (state.selected === tx.id ? " selected" : "");
    if (freshIds && freshIds.has(tx.id) && tx.source === "live") tr.classList.add("flash");
    const first = tx.rounds[0];
    const last = tx.rounds[tx.rounds.length - 1];
    const risk =
      first
        ? `<td class="score-cell"><span style="color:${LVL_COLOR[first.level]}">${first.risk_score}</span>` +
          (last && last !== first
            ? `<span style="color:#6a7894"> → </span><span style="color:${LVL_COLOR[last.level]}">${last.risk_score}</span>`
            : "") +
          `<small>${last.level}</small></td>`
        : `<td class="score-cell">—</td>`;
    tr.innerHTML =
      `<td>${fmtTime(tx.created_ts)}</td>` +
      `<td class="cust">${esc(tx.customer?.name || "—")}<small>${esc(tx.customer?.bank || "")}</small></td>` +
      `<td class="payee2">${esc(tx.merchant || tx.payee)}<small>${esc(tx.payee || "")}</small></td>` +
      `<td class="num">${inr(tx.amount)}</td>` +
      risk +
      `<td>${outcomeChain(tx)}</td>` +
      `<td>${stateTag(tx)}</td>` +
      settlementCell(tx) +
      opsCell(tx);
    tr.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      state.selected = tx.id;
      renderTable(null);
      renderDrawer(tx);
    });
    body.appendChild(tr);
  }
}

/* operator + drawer action buttons (delegated) */
document.addEventListener("click", async (e) => {
  const btn = e.target.closest("button.op-btn");
  if (!btn) return;
  const txId = btn.dataset.tx, act = btn.dataset.act;
  btn.disabled = true;
  const note = act === "override_approve"
    ? "Manual override after identity-verification call with customer"
    : "Risk operator confirmed the block as fraud";
  try {
    const res = await fetch("/api/v1/bank/actions", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ txn_id: txId, action: act, note }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "action failed");
    toast(act === "confirm_fraud"
      ? `${data.transaction.report_id} issued — fraud report registered`
      : "Blocked payment overridden & approved — sent to NPCI for settlement");
    state.selected = txId;
    await refresh(false);
  } catch (err) {
    toast("action failed: " + err.message, false);
    btn.disabled = false;
  }
});

/* ------------------------------ drawer -------------------------------- */
function roundCard(r, idx) {
  const color = LVL_COLOR[r.level];
  const pol = (r.policy || []).map((p) =>
    `<div class="pol ${r.action === "APPROVE" ? "p-ok" : ""}">• ${esc(p)}</div>`).join("");
  const contribs = (r.contributors || []).map((c) =>
    `<li><span>${esc(c.label)}<span class="m">${esc(c.value || "")} · ${esc(c.baseline || "")}</span></span>` +
    `<span class="sh">▲ ${c.share}%</span></li>`).join("");
  const signals = (r.signals && Object.keys(SIG_LABELS).some((k) => k in r.signals))
    ? `<div class="rl">Derived signals (SDK)<ul>${Object.keys(SIG_LABELS)
        .filter((k) => k in r.signals)
        .map((k) => `<li><span>${SIG_LABELS[k]}</span><span class="m">${Math.round(r.signals[k] * 100) / 100} ${SIG_UNITS[k] || ""}</span></li>`)
        .join("")}</ul></div>`
    : "";
  return `<div class="round-card">
    <div class="round-head">Round ${idx} — ${r.step === "challenge" ? "step-up re-auth" : "pre-authorization"}
      <b style="color:${color}">${r.risk_score}</b></div>
    <div class="round-bar"><i style="width:${Math.max(r.risk_score, 2)}%;background:${color}"></i></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:4px">
      <span class="pchip ${ACT_CLS[r.action]}">${r.level} · ${r.action}</span>
      <span class="src src-sample" style="border:1px solid #2a3f66;color:#8b97b0;padding:2px 7px;border-radius:99px">profile dev ×${r.deviation}</span>
    </div>
    ${contribs ? `<div class="rl">Why flagged<ul>${contribs}</ul></div>` : ""}
    ${pol}
    ${signals}
  </div>`;
}

function switchCard(tx) {
  const sw = tx.switch;
  if (!sw) return "";
  const statusMap = {
    settled: [`<span class="pchip p-approve">NPCI SETTLED</span>`, "Payment reached the UPI switch and settled."],
    not_reached: [`<span class="pchip p-block">NOT SENT</span>`, esc(sw.reason || "Blocked pre-authorization — never sent to the switch.")],
    in_review: [`<span class="pchip p-stepup">IN RISK REVIEW</span>`, "Held by the PSP until SecureUPI step-up resolves."],
  };
  const [chip, line] = statusMap[sw.status] || ["", ""];
  const utr = sw.utr
    ? `<div style="margin-top:6px"><span class="l" style="color:#7f8ea8;font-size:10px;text-transform:uppercase;letter-spacing:.6px">UTR</span><br>` +
      `<span style="font-family:var(--mono);color:#86efac;font-size:16px;font-weight:800">${esc(sw.utr)}</span></div>` : "";
  return `<div class="round-card" style="border-color:#14532d">
    <div class="round-head">UPI Switch — NPCI rail ${chip}</div>
    <div style="font-size:11.5px;color:#b9c4d9;margin-top:4px">${line}</div>
    ${utr}
    <div class="dr-meta" style="margin-top:6px">
      ${sw.ts ? "sent " + fmtTime(sw.ts) : ""}${sw.latency_ms ? " · switch round-trip " + sw.latency_ms + " ms" : ""}${sw.rail ? " · " + esc(sw.rail) : ""}
    </div>
  </div>`;
}

function renderDrawer(tx) {
  $("drawerEmpty").classList.add("hidden");
  const content = $("drawerContent");
  content.classList.remove("hidden");
  const audit = (tx.audit || []).map((a) =>
    `<li><b>${esc(a.action.replace(/_/g, " "))}</b> — ${esc(a.operator)}` +
    `<small>${fmtTime(a.ts)}${a.note ? " · " + esc(a.note) : ""}</small></li>`).join("");
  content.innerHTML = `
    <div class="dr-head">
      <div>
        <div class="dr-title">${esc(tx.merchant || "Payment")} · ${inr(tx.amount)}</div>
        <div class="dr-meta">${esc(tx.payee || "")} · ${tx.id}</div>
      </div>
      <div style="text-align:right">${stateTag(tx)}
        ${tx.report_id ? `<div style="margin-top:6px"><span class="rep-tag">${esc(tx.report_id)}</span></div>` : ""}
      </div>
    </div>
    <div class="dr-cust">
      <span><span class="l">Customer</span><br>${esc(tx.customer?.name || "—")}</span>
      <span><span class="l">Bank</span><br>${esc(tx.customer?.bank || "—")}</span>
      <span><span class="l">Device</span><br>${esc(tx.customer?.device || "—")}</span>
    </div>
    ${tx.rounds.map((r, i) => roundCard(r, i + 1)).join("")}
    ${switchCard(tx)}
    ${audit ? `<div class="audit"><div class="rl">Audit trail</div><ul>${audit}</ul></div>` : ""}
  `;
}

function showBanner(text, txnId) {
  const banner = $("banner");
  banner.classList.remove("hidden");
  banner.innerHTML = `<span>⚠️ ${text}</span><button class="mini-btn" id="bannerGo">Open case →</button>`;
  $("bannerGo").addEventListener("click", () => {
    const tx = state.tx.find((t) => t.id === txnId);
    if (tx) { state.selected = txnId; renderTable(null); renderDrawer(tx); }
    banner.classList.add("hidden");
  });
}

/* --------------------------- policy explorer -------------------------- */
function pct(x) { return (x * 100).toFixed(1) + "%"; }

function openPolicy() {
  $("policyModal").classList.remove("hidden");
  $("lowRange").value = state.policy.low_max;
  $("medRange").value = state.policy.medium_max;
  $("chalRange").value = state.policy.challenge_block_at;
  syncSliderLabels();
  updateExplore();
}

function closePolicy() { $("policyModal").classList.add("hidden"); }

function syncSliderLabels() {
  $("lowVal").textContent = $("lowRange").value;
  $("medVal").textContent = $("medRange").value;
  $("chalVal").textContent = $("chalRange").value;
  if (parseInt($("medRange").value, 10) <= parseInt($("lowRange").value, 10)) {
    $("medRange").value = Math.min(parseInt($("lowRange").value, 10) + 1, 100);
    $("medVal").textContent = $("medRange").value;
  }
}

async function updateExplore() {
  const low = parseInt($("lowRange").value, 10);
  const med = parseInt($("medRange").value, 10);
  let data;
  try {
    const res = await fetch(`/api/v1/policy/explore?low=${low}&med=${med}`);
    data = await res.json();
  } catch (e) { return; }
  const b = data.benign, p = data.positive;
  $("polMetrics").innerHTML =
    pm("Normal payments auto-approved (LOW)", b.low, "good") +
    pm("Normal payments get step-up / friction", b.med + b.high, "warn") +
    pm("High-risk payments CAUGHT (≥ step-up)", 1 - p.low, "good") +
    pm("High-risk payments silently auto-approved (slip)", p.low, "bad") +
    `<div class="pol-note">Held-out validation set: ${b.n} normal · ${p.n} high-risk sessions.
       Higher LOW bar = fewer normal frictions but more fraud slips through.</div>`;
  renderCurve(data.sweep, low);
}

function pm(label, share, cls) {
  const v = Math.max(0, Math.min(1, share));
  const color = cls === "good" ? "#22c55e" : cls === "bad" ? "#ef4444" : "#f59e0b";
  return `<div class="pm-bar"><span>${label}</span>
    <div class="track"><div class="fill ${cls}" style="width:${(v * 100).toFixed(1)}%;background:${color}"></div></div>
    <b style="font-family:var(--mono)">${pct(v)}</b></div>`;
}

function renderCurve(sweep, curLow) {
  const svg = $("curveSvg");
  const W = 340, H = 150, P = 8;
  if (!sweep || !sweep.length) { svg.innerHTML = ""; return; }
  const pts = sweep.map((s) => [
    P + (1 - s.benign_approved) * (W - 2 * P),
    H - P - s.risk_caught * (H - 2 * P),
  ]);
  const path = pts.map(([x, y], i) => (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1)).join(" ");
  const cur = sweep.find((s) => s.low_max === curLow) || sweep[0];
  const cx = P + (1 - cur.benign_approved) * (W - 2 * P);
  const cy = H - P - cur.risk_caught * (H - 2 * P);
  const grid = [0.25, 0.5, 0.75].map((f) =>
    `<line x1="${P}" y1="${H - P - f * (H - 2 * P)}" x2="${W - P}" y2="${H - P - f * (H - 2 * P)}" stroke="#141e33"/>`).join("");
  svg.innerHTML =
    grid +
    `<path d="${path}" fill="none" stroke="#7dd3fc" stroke-width="2"/>` +
    `<circle cx="${cx}" cy="${cy}" r="5" fill="#fbbf24" stroke="#713f12"/>`;
}

$("btnPolicy").addEventListener("click", openPolicy);
$("btnClosePolicy").addEventListener("click", closePolicy);
$("policyModal").addEventListener("click", (e) => { if (e.target.id === "policyModal") closePolicy(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePolicy(); });
["lowRange", "medRange", "chalRange"].forEach((id) => {
  $(id).addEventListener("input", () => {
    syncSliderLabels();
    clearTimeout(exploreTimer);
    exploreTimer = setTimeout(updateExplore, 120);
  });
});
$("btnResetPolicy").addEventListener("click", () => {
  state.policy = { ...DEFAULT_POLICY };
  $("lowRange").value = DEFAULT_POLICY.low_max;
  $("medRange").value = DEFAULT_POLICY.medium_max;
  $("chalRange").value = DEFAULT_POLICY.challenge_block_at;
  syncSliderLabels();
  savePolicy(true);
});
$("btnSavePolicy").addEventListener("click", () => savePolicy(false));

async function savePolicy(silentDefault) {
  const body = {
    low_max: parseFloat($("lowRange").value),
    medium_max: parseFloat($("medRange").value),
    challenge_block_at: parseFloat($("chalRange").value),
    hard_gate_amount: state.policy.hard_gate_amount,
  };
  try {
    const res = await fetch("/api/v1/policy", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "save failed");
    state.policy = data.policy;
    toast(silentDefault ? "Policy reset to defaults" :
      `Policy applied — LOW<${state.policy.low_max}, HIGH≥${state.policy.medium_max}, step-up blocks at ≥${state.policy.challenge_block_at}`);
    $("policyHint").textContent = "Applied. Run a payment on the demo page to see the new cut-offs in action.";
  } catch (e) {
    toast("save failed: " + e.message, false);
  }
}

/* ------------------------------- polling ------------------------------- */
async function refresh(autoOpen = false) {
  let res;
  try {
    res = await fetch("/api/v1/bank/transactions");
  } catch (e) {
    return;
  }
  const data = await res.json();
  const txs = data.transactions || [];
  const fresh = new Set(txs.filter((t) => !state.seen.has(t.id)).map((t) => t.id));
  txs.forEach((t) => state.seen.add(t.id));
  state.tx = txs;

  try {
    const pr = await fetch("/api/v1/profiles");
    const pd = await pr.json();
    state.profiles = pd.profiles || [];
  } catch (e) { /* keep old */ }

  renderKpis();
  renderCustomers();
  renderTable(autoOpen ? fresh : null);
  const hasSample = txs.some((t) => t.source === "sample");
  $("btnSample").textContent = hasSample ? "Refresh sample bank day" : "Load sample bank day (simulated)";

  if (autoOpen) {
    const liveBlocked = txs.filter((t) => fresh.has(t.id) && t.source === "live"
      && ["blocked", "fraud_reported"].includes(t.state));
    if (liveBlocked.length) {
      const tx = liveBlocked[0];
      state.selected = tx.id;
      renderTable(null);
      renderDrawer(tx);
      showBanner(`${inr(tx.amount)} blocked by SecureUPI → ${tx.merchant || tx.payee} (${tx.id}). Action required.`, tx.id);
    }
  }
  const sel = state.selected && state.tx.find((t) => t.id === state.selected);
  if (sel && !$("drawerContent").classList.contains("hidden")) renderDrawer(sel);
}

$("btnSample").addEventListener("click", async () => {
  try {
    const res = await fetch("/api/v1/bank/load-sample", { method: "POST" });
    const data = await res.json();
    if (data.ok) toast(`Loaded ${data.loaded} simulated transactions (clearly labelled)`);
    else toast("load failed", false);
  } catch (e) {
    toast("load failed: " + e.message, false);
  }
  state.seen.clear();
  await refresh(false);
});

/* -------------------------------- boot -------------------------------- */
(async function boot() {
  try {
    const res = await fetch("/api/v1/policy");
    const data = await res.json();
    state.policy = data.policy || { ...DEFAULT_POLICY };
  } catch (e) { /* defaults */ }
  await refresh(false);
  setInterval(() => refresh(true), 2500);
})();
