/* SecureUPI demo client.
 *
 * Mirrors the product pipeline:
 *   1. The "SDK" (this file) captures interaction signals on the payment flow
 *      (amount entry + PIN entry). In production this happens on-device and the
 *      raw stream never leaves the phone — only derived features are sent.
 *   2. POST /api/v1/assess  -> risk engine scores the payment pre-authorization.
 *   3. The demo UI enforces the returned action: APPROVE / STEP-UP / BLOCK.
 */
"use strict";

/* ------------------------------- helpers ------------------------------- */
const $ = (id) => document.getElementById(id);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const now = () => performance.now();
const pad2 = (n) => String(n).padStart(2, "0");
const clock = () => {
  const d = new Date();
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
};
const inr = (n) => "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 });
const stddev = (xs) => {
  if (xs.length < 2) return 0;
  const m = xs.reduce((a, b) => a + b, 0) / xs.length;
  return Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / xs.length);
};

/* --------------------------- personas -------------------------------- */
const PERSONAS = {
  aarav: { name: "Aarav Sharma", bank: "XYZ Bank", device: "Pixel 8 · Android 15" },
  ramesh: { name: "Ramesh Gupta", bank: "State Bank of India", device: "Redmi Note 12 · Android 13" },
};

/* ------------------------------- state -------------------------------- */
const KNOWN_PAYEES = new Set([
  "coffeehouse@upi", "merchant@upi", "kirana.store@upi",
  "groceries@upi", "electricity@ybl", "landlord@okhdfcbank",
]);
const FEATURE_META = [
  ["Amount entry time", "amount_fill_s", "s"],
  ["Amount corrections", "amount_corrections", ""],
  ["Longest typing pause", "amount_max_pause_s", "s"],
  ["Review time before Pay", "pay_dwell_s", "s"],
  ["PIN entry speed", "pin_cps", "digits/s"],
  ["Longest PIN pause", "pin_max_pause_s", "s"],
  ["PIN re-entries", "pin_resets", ""],
  ["Tap-hold variability", "pin_hold_std_ms", "ms"],
  ["Tap accuracy offset", "pin_tap_offset_px", "px"],
];

const state = {
  running: false,         // autoplay in progress
  abort: null,
  sessionId: null,
  step: "initial",
  scenarioName: "",
  persona: "aarav",
  amount: 0,
  payee: "", vpa: "",
  signals: null,          // last captured signals
  typical: null,          // personalised "your typical" baselines from the engine
};

/* ---------------------------- capture buffers -------------------------- */
const cap = {
  // amount
  aKeyTimes: [], aFirst: 0, aLast: 0, aCorrections: 0, aLastLen: 0,
  // pin
  pinTaps: [], pinResets: 0, pendingDown: null,
};

function resetCapture() {
  cap.aKeyTimes = []; cap.aFirst = 0; cap.aLast = 0; cap.aCorrections = 0;
  cap.pinTaps = []; cap.pinResets = 0; cap.pendingDown = null;
  state.signals = null;
}

/* ------------------------------ DOM refs ------------------------------ */
const refs = {
  amountInput: $("amountInput"), payBtn: $("payBtn"), personaSel: $("personaSel"),
  payeeChip: $("payeeChip"), merchantName: $("merchantName"),
  merchantVpa: $("merchantVpa"), merchantAvatar: $("merchantAvatar"),
  amountHint: $("amountHint"),
  screenPay: $("screenPay"), screenPin: $("screenPin"),
  pinDots: $("pinDots"), pinTitle: $("pinTitle"), pinSub: $("pinSub"),
  pinAmount: $("pinAmount"), pinPayee: $("pinPayee"),
  overlayBusy: $("overlayBusy"), overlayApprove: $("overlayApprove"),
  overlayStepup: $("overlayStepup"), overlayBlock: $("overlayBlock"),
  okText: $("okText"), okTxn: $("okTxn"), blockText: $("blockText"),
  stepupText: $("stepupText"),
  attemptLabel: $("attemptLabel"), gaugeScore: $("gaugeScore"),
  gaugeFill: $("gaugeFill"), levelPill: $("levelPill"), actionPill: $("actionPill"),
  deviationChip: $("deviationChip"), whyPanel: $("whyPanel"),
  whyList: $("whyList"), policyList: $("policyList"),
  signalGrid: $("signalGrid"), ticker: $("ticker"),
  historyBody: $("historyBody"), modelMeta: $("modelMeta"),
  modelStats: $("modelStats"), weightsList: $("weightsList"),
  chkScreenShare: $("chkScreenShare"), chkIntegrity: $("chkIntegrity"),
};

/* ------------------------------ ticker -------------------------------- */
function logLine(kind, text) {
  const div = document.createElement("div");
  if (kind === "dim") div.className = "t-dim";
  else if (kind === "warn") div.className = "t-warn";
  else if (kind === "bad") div.className = "t-bad";
  const ts = document.createElement("span");
  ts.className = "t-dim";
  ts.textContent = `[${clock()}] `;
  div.appendChild(ts);
  div.appendChild(document.createTextNode(text));
  refs.ticker.appendChild(div);
  while (refs.ticker.childNodes.length > 160) refs.ticker.removeChild(refs.ticker.firstChild);
  refs.ticker.scrollTop = refs.ticker.scrollHeight;
}

/* ------------------------------ money typing --------------------------- */
function setMerchant(name, vpa) {
  refs.merchantName.textContent = name;
  refs.merchantVpa.textContent = vpa;
  refs.merchantAvatar.textContent = (name[0] || "?").toUpperCase();
  state.payee = name;
  state.vpa = vpa;
  updatePayeeChip();
}

function updatePayeeChip() {
  const known = KNOWN_PAYEES.has(state.vpa);
  refs.payeeChip.textContent = known ? "known payee" : "NEW payee";
  refs.payeeChip.className = "chip " + (known ? "chip-k" : "chip-u");
}

/* --------------------------- amount capture --------------------------- */
refs.amountInput.addEventListener("input", () => {
  const raw = refs.amountInput.value;
  const digits = raw.replace(/\D/g, "");
  if (digits !== raw) refs.amountInput.value = digits;
  const len = digits.length;
  if (len > cap.aLastLen) {
    const t = now();
    if (!cap.aFirst) cap.aFirst = t;
    cap.aKeyTimes.push(t);
    cap.aLast = t;
  } else if (len < cap.aLastLen) {
    cap.aCorrections += cap.aLastLen - len;
  }
  cap.aLastLen = len;
  refs.payBtn.disabled = len === 0;
});

function amountFeatures() {
  const times = cap.aKeyTimes;
  let maxPause = 0;
  for (let i = 1; i < times.length; i++) maxPause = Math.max(maxPause, (times[i] - times[i - 1]) / 1000);
  const fillS = times.length > 1 ? (times[times.length - 1] - times[0]) / 1000 : 0;
  return {
    amount_fill_s: round2(fillS),
    amount_corrections: cap.aCorrections,
    amount_max_pause_s: round2(Math.min(maxPause, 12)),
    pay_dwell_s: round2(Math.min(state.payDwell || 0, 12)),
  };
}

const round2 = (x) => Math.round(x * 100) / 100;

/* ------------------------------ PIN pad ------------------------------- */
function pinDot(filled, i) {
  const dot = refs.pinDots.children[i];
  dot.classList.toggle("filled", filled);
}

function resetPinPad() {
  cap.pinTaps = []; cap.pinResets = 0;
  for (let i = 0; i < 4; i++) pinDot(false, i);
}

function personaTag() {
  const p = PERSONAS[state.persona] || PERSONAS.aarav;
  return `${p.name.split(" ")[0]} · ${p.bank.split(" ")[0]}`;
}

function showPin(step, amountText) {
  state.step = step;
  refs.screenPay.classList.add("hidden");
  refs.screenPin.classList.remove("hidden");
  if (step === "initial") {
    refs.attemptLabel.textContent =
      `Attempt 1 · pre-authorization${state.scenarioName ? " · " + state.scenarioName : " (manual)"} · [${personaTag()}]`;
  } else {
    refs.attemptLabel.textContent = `Attempt 2 · step-up re-authentication · [${personaTag()}]`;
  }
  $$(".pinpad .key").forEach((k) => (k.disabled = false));
  refs.pinTitle.textContent = step === "initial" ? "Enter UPI PIN" : "Confirm your PIN";
  refs.pinSub.innerHTML =
    `to pay <b>${amountText}</b> to <span>${state.payee}</span>` +
    (step === "challenge" ? " &nbsp;&middot;&nbsp; step-up verification" : "");
  resetPinPad();
  logLine("warn",
    step === "initial"
      ? "SDK: observing PIN entry behaviour…"
      : "SDK: step-up round — watching for calm, steady PIN entry…");
  refs.pinDots.children[0].focus?.();
}

refs.pinDots.querySelectorAll(".dot-pin").forEach(() => { /* decorative */ });

function onPointerDown(e) {
  const target = e.target.closest(".key");
  if (!target || target.dataset.key === "" || refs.screenPin.classList.contains("hidden")) return;
  cap.pendingDown = {
    t: now(), x: e.clientX, y: e.clientY, target, pointerType: e.pointerType,
    hold: Number.isFinite(e.detail) && e.detail > 0 ? e.detail : null,  // scenario taps carry their hold via detail
  };
}

function onPointerUp(e) {
  const target = e.target.closest(".key");
  if (!target || !cap.pendingDown || cap.pendingDown.target !== target) return;
  const key = target.dataset.key;
  if (key === "") return;
  const t = now();
  const rect = target.getBoundingClientRect();
  const cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
  const dx = cap.pendingDown.x - cx, dy = cap.pendingDown.y - cy;
  let offset = Math.hypot(dx, dy);
  // Desktop mouse: clicking anywhere on a key is *intentional* — on a phone,
  // large miss-distance only happens with tremor. Map mouse offset to a
  // touch-realistic figure so free-play stays honest on a laptop demo.
  if (cap.pendingDown.pointerType === "mouse") offset = Math.min(offset * 0.25, 5.5);
  // Scenario taps stamp their intended hold into the event; real finger taps
  // measure the actual press duration.
  const hold = cap.pendingDown.hold ?? (t - cap.pendingDown.t);
  cap.pendingDown = null;
  pressKey(key, { t, hold, offset });
}

function pressKey(key, ev = {}) {
  if (key === "back") {
    if (cap.pinTaps.length) {
      cap.pinResets += 1;
      cap.pinTaps = [];
      logLine("warn", "SDK: PIN entry cleared & restarted (re-entry signal)");
    }
    for (let i = 0; i < 4; i++) pinDot(false, i);
    return;
  }
  if (cap.pinTaps.length >= 4) return;
  const prevT = cap.pinTaps.length ? cap.pinTaps[cap.pinTaps.length - 1].t : null;
  cap.pinTaps.push({
    t: ev.t ?? now(),
    hold: ev.hold ?? 70,
    offset: ev.offset ?? 2,
    gap: prevT ? (ev.t ?? now()) - prevT : 0,
    key,
  });
  logLine("dim", `SDK: PIN key ${key} tapped — hold ${Math.round(ev.hold ?? 70)} ms, offset ${(ev.offset ?? 2).toFixed(1)} px`);
  for (let i = 0; i < cap.pinTaps.length; i++) pinDot(true, i);
  if (cap.pinTaps.length === 4) {
    refs.pinDots.parentElement.querySelectorAll(".key").forEach((k) => (k.disabled = true));
    setTimeout(() => assess(), 240);
  }
}

function pinFeatures() {
  const taps = cap.pinTaps;
  if (!taps.length) return { pin_cps: 0, pin_max_pause_s: 0, pin_resets: 0, pin_hold_std_ms: 0, pin_tap_offset_px: 0 };
  const t1 = taps[0].t, t4 = taps[taps.length - 1].t;
  const span = Math.max((t4 - t1) / 1000, 0.12);
  const cps = taps.length / span;
  let maxPause = 0;
  for (const tap of taps) maxPause = Math.max(maxPause, tap.gap / 1000);
  return {
    pin_cps: round2(Math.min(cps, 8)),
    pin_max_pause_s: round2(Math.min(maxPause, 12)),
    pin_resets: cap.pinResets,
    pin_hold_std_ms: round2(stddev(taps.map((t) => t.hold))),
    pin_tap_offset_px: round2(taps.reduce((a, t) => a + t.offset, 0) / taps.length),
  };
}

/* --------------------------- pay flow buttons ------------------------- */
refs.payBtn.addEventListener("click", () => {
  const amount = parseInt(refs.amountInput.value || "0", 10);
  if (!amount) return;
  state.amount = amount;
  state.payDwell = cap.aLast ? (now() - cap.aLast) / 1000 : 0.4;
  showPin("initial", inr(amount));
  logLine("warn", `User pressed AUTHENTICATE & PAY for ${inr(amount)} — assessing pre-authorization risk`);
});

/* ------------------------------- assess ------------------------------- */
async function assess() {
  const pin = pinFeatures();
  const amt = amountFeatures();
  const signals = { ...amt, ...pin };
  state.signals = signals;
  renderSignals(signals);

  refs.screenPin.classList.add("hidden");
  refs.overlayBusy.classList.remove("hidden");

  const payload = {
    session_id: state.sessionId,
    step: state.step,
    customer: PERSONAS[state.persona] || PERSONAS.aarav,
    context: {
      amount: state.amount,
      payee: state.vpa,
      payee_name: state.payee,
      new_payee: !KNOWN_PAYEES.has(state.vpa),
    },
    signals,
    detections: {
      screen_share: refs.chkScreenShare.checked,
      integrity_fail: refs.chkIntegrity.checked,
    },
  };
  logLine("dim", `SDK → engine: ${JSON.stringify(signals)}`);

  try {
    const res = await fetch("/api/v1/assess", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "engine error");
    if (data.profile_typical) {
      state.typical = data.profile_typical;   // per-customer learned baseline
      if (state.signals) renderSignals(state.signals);
    }
    renderDecision(data);
  } catch (err) {
    logLine("bad", `engine error: ${err.message}`);
    refs.overlayBusy.classList.add("hidden");
    refs.screenPay.classList.remove("hidden");
  }
}

/* --------------------------- decision render -------------------------- */
function renderDecision(r) {
  refs.overlayBusy.classList.add("hidden");
  logLine(r.level === "LOW" ? "dim" : r.level === "MEDIUM" ? "warn" : "bad",
    `ENGINE → ${r.level} risk score ${r.risk_score} (${r.action})`);

  refs.gaugeScore.textContent = r.risk_score;
  refs.gaugeFill.style.width = r.risk_score + "%";
  refs.levelPill.textContent = `RISK ${r.level}`;
  refs.levelPill.className = "lvl lvl-" + r.level;
  refs.deviationChip.textContent = `profile deviation ×${r.profile_deviation}`;

  const actColors = { APPROVE: "#22c55e", "STEP-UP": "#f59e0b", BLOCK: "#ef4444" };
  refs.actionPill.innerHTML =
    `<span class="chipact" style="background:${actColors[r.action] || "#888"}">${r.action}</span>` +
    (r.action === "APPROVE" ? "authorize this payment" :
     r.action === "STEP-UP" ? "additional verification required" : "payment refused");

  // explainability
  if (r.top_contributors && r.top_contributors.length) {
    refs.whyPanel.hidden = false;
    refs.whyList.innerHTML = "";
    for (const c of r.top_contributors) {
      const li = document.createElement("li");
      li.innerHTML = `<span>${c.label}</span><span class="meta">${c.value} &middot; ${c.baseline}</span>` +
        `<span class="share">&#9650; ${c.share}%</span>`;
      refs.whyList.appendChild(li);
    }
  } else {
    refs.whyPanel.hidden = true;
    refs.whyList.innerHTML = "";
  }
  refs.policyList.innerHTML = "";
  for (const p of (r.policy || [])) {
    const li = document.createElement("li");
    if (r.action === "APPROVE") li.className = "p-ok";
    li.textContent = "• " + p;
    refs.policyList.appendChild(li);
  }

  // phone outcome
  if (r.action === "APPROVE") {
    refs.okText.textContent = `${inr(state.amount)} paid to ${state.payee}`;
    refs.okTxn.textContent = "UTR " + Math.floor(100000000000 + Math.random() * 899999999999);
    refs.overlayApprove.classList.remove("hidden");
    KNOWN_PAYEES.add(state.vpa);
    updatePayeeChip();
    logLine("dim", `UPI: payment authorized → ${inr(state.amount)} to ${state.vpa}`);
  } else if (r.action === "STEP-UP") {
    refs.stepupText.textContent = r.level === "HIGH"
      ? "High-risk context detected before authorization. This does NOT mean fraud — verify it's really you by re-entering your UPI PIN calmly."
      : "This payment looks unusual for your profile (risk " + r.risk_score + "). Re-enter your UPI PIN calmly to confirm it's really you.";
    refs.attemptLabel.textContent = "Attempt 1 · pre-authorization · " + (state.scenarioName || "manual");
    refs.overlayStepup.classList.remove("hidden");
  } else { // BLOCK
    refs.blockText.textContent = "High-risk context confirmed during step-up. The payment was NOT authorized.";
    refs.attemptLabel.textContent = "Attempt 2 · step-up · BLOCKED";
    refs.overlayBlock.classList.remove("hidden");
    logLine("bad", `BLOCKED ${inr(state.amount)} to ${state.vpa} — suspected fraud context`);
  }
  refreshHistory();
}

$("btnStepup").addEventListener("click", () => {
  refs.overlayStepup.classList.add("hidden");
  showPin("challenge", inr(state.amount));
  const last = state.lastScenario;
  if (last && last !== "free" && last !== "coffee" && SCENARIOS[last]) {
    setTimeout(() => simulateChallenge(last), 600);
  } else {
    logLine("dim", "step-up: type your PIN calmly to confirm it's really you");
  }
});

async function simulateChallenge(name) {
  const sc = SCENARIOS[name];
  const anxious = name === "scam" || name === "duress";
  state.running = true;
  state.abort = { aborted: false };
  const token = state.abort;
  $$(".scn").forEach((b) => (b.disabled = true));
  refs.amountInput.disabled = true;
  logLine("warn", anxious
    ? "step-up: behaviour still anxious — pauses, tremor taps…"
    : "step-up: calm, steady re-authentication…");
  const sleep = (ms) => new Promise((res) => {
    const iv = setInterval(() => { if (token.aborted) { clearInterval(iv); res(); } }, 40);
    setTimeout(() => { clearInterval(iv); res(); }, Math.max(ms, 0));
  });
  await sleep(400);
  const delays = anxious ? sc.pin.delays : [320, 310, 300, 330];
  const holds = anxious ? sc.pin.hold : [72, 78, 65, 70];
  const offsets = anxious ? sc.pin.offset : [2.0, 2.4, 2.0, 2.2];
  const PIN = "7241";
  // Anxious re-entry: type 1 digit, clear, then the full PIN (real reset).
  const taps = [{ k: PIN[0] }, { k: "back", reset: true }];
  for (const d of PIN) taps.push({ k: d });
  let tapIdx = 0;
  for (let i = 0; i < taps.length; i++) {
    if (token.aborted) return finishRun();
    const tp = taps[i];
    if (tp.reset) {
      await sleep(700);
      dispatchTap(".pinpad .key[data-key='back']", 150, 4);
      await sleep(600);
      logLine("warn", "SDK: step-up PIN cleared & restarted — still unsteady");
      continue;
    }
    await sleep(delays[tapIdx % PIN.length] + rnd(60));
    dispatchTap(".pinpad .key[data-key='" + tp.k + "']",
      holds[tapIdx % PIN.length] + rnd(25), offsets[tapIdx % PIN.length]);
    tapIdx++;
  }
  await sleep(1200);
  finishRun();
}

$("btnDoneA").addEventListener("click", resetPayment);
$("btnReset").addEventListener("click", resetPayment);
$("btnReport").addEventListener("click", async () => {
  const btn = $("btnReport");
  btn.disabled = true;
  btn.textContent = "Reporting…";
  try {
    const res = await fetch("/api/v1/bank/report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId }),
    });
    const data = await res.json();
    if (res.ok && data.transaction && data.transaction.report_id) {
      btn.textContent = `Reported · ${data.transaction.report_id} ✓`;
      logLine("warn", `Fraud report ${data.transaction.report_id} filed — visible in the PSP console`);
    } else {
      btn.textContent = "Reported ✓";
      logLine("warn", "Fraud report filed with the bank (simulated) — beneficiary flagged for review");
    }
  } catch (e) {
    btn.textContent = "Reported ✓";
    btn.disabled = false;
    logLine("bad", `report failed: ${e.message}`);
  }
});

function resetPayment() {
  if (state.abort) { state.abort.aborted = true; state.abort = null; }
  state.running = false;
  state.typical = null;
  $$(".overlay").forEach((o) => o.classList.add("hidden"));
  refs.screenPin.classList.add("hidden");
  refs.screenPay.classList.remove("hidden");
  refs.payBtn.disabled = !(refs.amountInput.value || "").length;
  refs.payBtn.disabled = false;
  resetCapture();
  refs.attemptLabel.textContent = "idle — awaiting payment";
  refs.gaugeScore.textContent = "—";
  refs.gaugeFill.style.width = "0%";
  refs.levelPill.textContent = "NO ASSESSMENT YET";
  refs.levelPill.className = "lvl lvl-neutral";
  refs.actionPill.textContent = "waiting for a payment…";
  refs.deviationChip.textContent = "profile deviation —";
  refs.whyPanel.hidden = true;
  refs.policyList.innerHTML = "";
  renderSignals(null);
}

/* --------------------------- signal grid ------------------------------ */
let benignProfile = {};
function renderSignals(signals) {
  if (!signals) {
    refs.signalGrid.innerHTML = `<div class="sig"><span class="v" style="color:#54627d">no signals yet — run a scenario</span></div>`;
    return;
  }
  refs.signalGrid.innerHTML = "";
  for (const [label, key, unit] of FEATURE_META) {
    const v = signals[key];
    const typical = (state.typical && state.typical[key] !== undefined) ? state.typical[key] : benignProfile[key];
    const div = document.createElement("div");
    div.className = "sig";
    let vText;
    if (key === "amount_corrections") vText = String(v);
    else if (key === "pin_cps") vText = v.toFixed(2) + " " + unit;
    else if (unit === "s") vText = v.toFixed(1) + " " + unit;
    else vText = v + " " + unit;
    div.innerHTML =
      `<span class="k">${label}</span><span class="v">${vText}</span>` +
      `<span class="b">your typical ≈ ${typical !== undefined ? round2(typical) + " " + unit : "—"}</span>`;
    refs.signalGrid.appendChild(div);
  }
  const det = [];
  if (refs.chkScreenShare.checked) det.push("screen-share ACTIVE");
  if (refs.chkIntegrity.checked) det.push("integrity FAIL");
  if (det.length) {
    const div = document.createElement("div");
    div.className = "sig hot";
    div.innerHTML = `<span class="k">detections</span><span class="v">${det.join(" · ")}</span><span class="b">simulated SDK</span>`;
    refs.signalGrid.appendChild(div);
  }
}

/* ----------------------------- scenarios ------------------------------ */
const SCENARIOS = {
  coffee: {
    name: "Coffee ₹250 (calm)", persona: "aarav",
    merchant: "Coffee House", vpa: "coffeehouse@upi", amount: "250",
    fill: { chars: 0.62 }, dwell: 0.9,
    pin: { delays: [340, 330, 300, 320], hold: [70, 80, 65, 75], offset: [1.5, 2.2, 1.9, 2.6] },
  },
  senior: {
    name: "Senior ₹450 (slow but smooth)", persona: "ramesh",
    merchant: "Priya Sharma", vpa: "savings@okhdfcbank", amount: "450",
    fill: { chars: 1.45 }, dwell: 2.2,
    pin: { delays: [480, 420, 460, 520], hold: [90, 110, 100, 105], offset: [3.2, 3.8, 3.1, 3.5] },
  },
  big2am: {
    name: "2 AM ₹45,000 to new payee", persona: "aarav",
    merchant: "Urban Nidhi Finance", vpa: "urbannidhi@icici", amount: "45000",
    fill: { chars: 0.55 }, dwell: 1.3,
    pin: { delays: [320, 310, 340, 305], hold: [65, 72, 60, 68], offset: [1.8, 2.1, 1.6, 2.0] },
  },
  scam: {
    name: "'Verify account' ₹50,000 scam", persona: "aarav",
    merchant: "RBI Refund Desk", vpa: "refund.verify@icici", amount: "50000",
    fill: { chars: 1.5, correctionAt: 4, correctionPause: 2.8, correctionGap: 0.8 },
    dwell: 4.6,
    pin: { delays: [900, 2400, 950, 1250], hold: [160, 210, 145, 235], offset: [7.5, 9.2, 6.8, 8.4], resetsAt: 1 },
    screenShare: true,
  },
  duress: {
    name: "Duress ₹40,000", persona: "aarav",
    merchant: "Cash Back Office", vpa: "cashback.office@hdfcbank", amount: "40000",
    fill: { chars: 1.15, correctionAt: 3, correctionPause: 1.6, correctionGap: 0.5 },
    dwell: 1.8,
    pin: { delays: [750, 1450, 820, 2400], hold: [200, 340, 180, 300], offset: [11, 14, 10, 15], resetsAt: 2 },
  },
};

async function runScenario(name) {
  if (state.running) return;
  const sc = SCENARIOS[name];
  if (!sc) { logLine("warn", "free play — type an amount and pay"); return; }
  if (name === "free") { resetPayment(); logLine("dim", "manual mode ready — enter amount, press Pay, tap your PIN"); return; }

  const sleep = (ms) => new Promise((res) => {
    const iv = setInterval(() => {
      if (token.aborted) { clearInterval(iv); res(); }
    }, 40);
    setTimeout(() => { clearInterval(iv); res(); }, Math.max(ms, 0));
  });

  resetPayment();                       // clears prior autoplay state (aborts old tokens)
  state.running = true;
  state.abort = { aborted: false };     // fresh token AFTER reset — reset must not kill us
  const token = state.abort;
  state.scenarioName = sc.name;
  state.lastScenario = name;
  if (sc.persona) {
    state.persona = sc.persona;         // e.g. the senior scenario = Ramesh Gupta
    refs.personaSel.value = sc.persona;
  }
  state.typical = null;
  $$(".scn").forEach((b) => (b.disabled = true));
  refs.amountInput.disabled = true;

  // simulated SDK detections for this scenario
  refs.chkScreenShare.checked = !!sc.screenShare;
  refs.chkIntegrity.checked = !!sc.integrityFail;
  renderSignals({ amount_fill_s: 0, amount_corrections: 0, amount_max_pause_s: 0,
    pay_dwell_s: 0, pin_cps: 0, pin_max_pause_s: 0, pin_resets: 0,
    pin_hold_std_ms: 0, pin_tap_offset_px: 0 });

  logLine("dim", `DEMO: scenario "${sc.name}"`);
  logLine("warn", sc.screenShare
    ? "SDK detection: screen-share / remote view ACTIVE during payment flow"
    : "SDK detection: no screen-share, device integrity OK");

  setMerchant(sc.merchant, sc.vpa);
  refs.amountHint.textContent = "simulating…";
  refs.amountInput.value = "";
  cap.aLastLen = 0;

  // ---- amount entry -------------------------------------------------
  await sleep(400);
  const digits = sc.amount;
  const baseDelay = sc.fill.chars * 1000;
  for (let i = 0; i < digits.length; i++) {
    if (token.aborted) return finishRun();
    refs.amountInput.value = digits.slice(0, i + 1);
    refs.amountInput.dispatchEvent(new Event("input", { bubbles: true }));
    const extraPause = sc.fill.correctionAt === i + 1 ? sc.fill.correctionPause : 0;
    await sleep(baseDelay + extraPause * 1000 + rnd(120));
  }
  if (sc.fill.correctionAt) {
    // visible hesitation: delete the last digit, pause, then retype it
    if (token.aborted) return finishRun();
    refs.amountInput.value = digits.slice(0, digits.length - 1);
    refs.amountInput.dispatchEvent(new Event("input", { bubbles: true }));
    await sleep(sc.fill.correctionGap * 1000 + rnd(100));
    refs.amountInput.value = digits;
    refs.amountInput.dispatchEvent(new Event("input", { bubbles: true }));
    refs.amountHint.textContent = "hesitation + correction detected";
    logLine("warn", "SDK: amount corrected after a long pause (dictated entry?)");
    await sleep(350);
  }
  refs.amountHint.textContent = "amount entered — reviewing before Pay";
  refs.payBtn.disabled = false;

  await sleep(sc.dwell * 1000);
  if (token.aborted) return finishRun();
  refs.payBtn.click();

  // ---- PIN entry ----------------------------------------------------
  await sleep(500);
  const PIN = "7241";
  // Build the tap sequence. Hesitation scenarios start typing, then clear &
  // retype (resetsAt times) so the pin_resets signal is real, not narrated:
  //   resetsAt=1: type 1 digit, clear, then the full PIN
  //   resetsAt=2: type 1, clear, type 2, clear, then the full PIN
  const taps = [];
  for (let r = 0; r < (sc.pin.resetsAt || 0); r++) {
    for (let i = 0; i < Math.min(r + 1, 2); i++) taps.push({ k: PIN[i] });
    taps.push({ k: "back", reset: true });
  }
  for (const d of PIN) taps.push({ k: d });
  let tapIdx = 0;
  for (let i = 0; i < taps.length; i++) {
    if (token.aborted) return finishRun();
    const tp = taps[i];
    if (tp.reset) {
      await sleep(700);
      dispatchTap(".pinpad .key[data-key='back']", 150, 3);
      await sleep(600);
      logLine("warn", "SDK: PIN cleared & restarted — hesitation before completing");
      continue;
    }
    await sleep(sc.pin.delays[tapIdx % PIN.length] + rnd(60));
    dispatchTap(".pinpad .key[data-key='" + tp.k + "']",
      sc.pin.hold[tapIdx % PIN.length] + rnd(25), sc.pin.offset[tapIdx % PIN.length]);
    tapIdx++;
  }
  // engine answers async (assess() fires ~240 ms after 4th tap)
  await sleep(900);
  finishRun();
}

function finishRun() {
  state.running = false;
  state.abort = null;
  refs.amountInput.disabled = false;
  $$(".scn").forEach((b) => (b.disabled = false));
  refs.amountHint.textContent = "";
}

function rnd(x) { return Math.random() * x; }

function dispatchTap(sel, holdMs, offset) {
  const el = typeof sel === "string" ? document.querySelector(sel) : sel;
  if (!el) return;
  const rect = el.getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const ang = Math.random() * Math.PI * 2;
  const x = cx + offset * Math.cos(ang);
  const y = cy + offset * Math.sin(ang);
  // Scenario taps simulate a FINGER on a touchscreen — keep tremor offsets.
  // pointerdown + pointerup fire back-to-back (no chained timer, so throttled
  // background tabs can't drop taps); the intended hold travels in `detail`
  // and the loop's pacing between taps still drives pause/CPs signals.
  const opts = { bubbles: true, clientX: x, clientY: y, pointerType: "touch", detail: holdMs };
  el.dispatchEvent(new PointerEvent("pointerdown", opts));
  el.dispatchEvent(new PointerEvent("pointerup", opts));
}

/* --------------------------- history / model ------------------------- */
async function refreshHistory() {
  try {
    const res = await fetch("/api/v1/events");
    const data = await res.json();
    const rows = (data.events || []).slice(0, 30);
    if (!rows.length) {
      refs.historyBody.innerHTML = `<tr><td colspan="6" class="empty">no payments evaluated yet — run a scenario</td></tr>`;
      return;
    }
    refs.historyBody.innerHTML = "";
    for (const ev of rows) {
      const tr = document.createElement("tr");
      const stepTag = ev.step === "challenge" ? " <span style='color:#7dd3fc'>·step2</span>" : "";
      tr.innerHTML =
        `<td>${(ev.ts || "").slice(11, 19)}</td>` +
        `<td>${ev.payee}</td>` +
        `<td class="num">${inr(ev.amount)}</td>` +
        `<td class="num">${ev.risk_score}</td>` +
        `<td><span class="tag tag-${ev.level}">${ev.level}</span>${stepTag}</td>` +
        `<td><span class="tag tag-${ev.action}">${ev.action}</span></td>`;
      refs.historyBody.appendChild(tr);
    }
  } catch (e) { /* console only */ }
}

async function loadModel() {
  try {
    const res = await fetch("/api/v1/model");
    const m = await res.json();
    benignProfile = m.benign_profile || {};
    refs.modelMeta.textContent = `model v${m.version} · trained ${(m.trained_at_utc || "").slice(0, 10)}`;
    const pct = (x) => (x * 100).toFixed(1) + "%";
    refs.modelStats.innerHTML =
      `<div class="m"><b>${pct(m.accuracy)}</b><span>validation accuracy</span></div>` +
      `<div class="m"><b>${pct(m.risk_recall)}</b><span>high-risk recall</span></div>` +
      `<div class="m"><b>${pct(m.benign_specificity)}</b><span>normal payments approved</span></div>` +
      `<div class="m"><b>${pct(m.benign_level_low_share)}</b><span>normal payments LOW risk</span></div>` +
      `<div class="m"><b>${m.n_train.toLocaleString()}</b><span>training sessions</span></div>`;
    refs.weightsList.innerHTML = "";
    for (const w of m.weights.slice(0, 7)) {
      const chip = document.createElement("span");
      chip.className = "w-chip";
      chip.textContent = w.label + " ";
      const b = document.createElement("b");
      b.textContent = (w.direction === "higher" ? "▲" : "▼") + " strong";
      chip.appendChild(b);
      refs.weightsList.appendChild(chip);
    }
  } catch (e) { /* offline fallback */ }
}

$("btnClearEvents").addEventListener("click", async () => {
  await fetch("/api/v1/events/reset", { method: "POST" });
  refreshHistory();
  logLine("dim", "risk-event log cleared");
});

$$(".scn").forEach((b) => {
  b.addEventListener("click", () => {
    state.sessionId = "s-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    if (b.dataset.scenario === "free") {
      resetPayment();
      state.sessionId = null;
      state.lastScenario = "free";
      state.scenarioName = "";
      logLine("dim", "manual mode — type an amount, press Pay, enter your real PIN rhythm");
      return;
    }
    runScenario(b.dataset.scenario);
  });
});

/* persona selector */
refs.personaSel.addEventListener("change", () => {
  state.persona = refs.personaSel.value;
  state.typical = null;
  const p = PERSONAS[state.persona];
  logLine("dim", `persona: ${p.name} (${p.bank}) — baseline profile active`);
  renderSignals(state.signals);
});

/* toggles */
[refs.chkScreenShare, refs.chkIntegrity].forEach((c) => {
  c.addEventListener("change", () => {
    logLine("warn",
      (c.id === "chkScreenShare" ? "detection: screen-share " : "detection: device integrity ") +
      (c.checked ? "ACTIVE" : "cleared"));
    renderSignals(state.signals);
  });
});

/* keyboard: Enter moves to Pay */
refs.amountInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !refs.payBtn.disabled) refs.payBtn.click();
});

/* ------------------------------- boot --------------------------------- */
(function init() {
  document.addEventListener("pointerdown", onPointerDown);
  document.addEventListener("pointerup", onPointerUp);
  setMerchant("Coffee House", "coffeehouse@upi");
  resetPayment();
  loadModel();
  refreshHistory();
  setInterval(refreshHistory, 4000);
})();
