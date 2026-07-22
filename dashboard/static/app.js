const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let currentConfigName = null;
let eventSource = null;
let lssHistory = {};
let fighterColors = {};
let chartMaxRounds = 5;
let currentBatchId = null;
let currentRunIds = [];
let selectedRunId = null;
let runsPollTimer = null;
const COLOR_PALETTE = ["#5ae", "#c5e", "#7ec", "#ec7"];

// --- Tab navigation ---
$$(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab-btn").forEach((b) => b.classList.remove("active"));
    $$(".tab").forEach((t) => t.classList.remove("active"));
    btn.classList.add("active");
    $("#" + btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "results") loadExperiments();
  });
});

// --- Configs ---
async function loadConfigs() {
  const res = await fetch("/api/configs");
  const configs = await res.json();
  const list = $("#config-list");
  list.innerHTML = "";
  for (const c of configs) {
    const li = document.createElement("li");
    li.textContent = c.name;
    li.dataset.name = c.name;
    li.addEventListener("click", () => selectConfig(c.name, li));
    list.appendChild(li);
  }
}

async function selectConfig(name, li) {
  $$("#config-list li").forEach((x) => x.classList.remove("active"));
  if (li) li.classList.add("active");
  const res = await fetch("/api/configs/" + name);
  const text = await res.text();
  $("#config-name").textContent = name;
  $("#config-editor").value = text;
  currentConfigName = name;
  $("#config-status").textContent = "";
}

$("#save-config-btn").addEventListener("click", async () => {
  if (!currentConfigName) {
    $("#config-status").textContent = "No config selected.";
    return;
  }
  const res = await fetch("/api/configs/" + currentConfigName, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: $("#config-editor").value }),
  });
  const data = await res.json();
  $("#config-status").textContent = "Saved: " + data.name;
  loadConfigs();
});

$("#new-config-btn").addEventListener("click", () => {
  const name = prompt("Config name (e.g. myfight.toml):");
  if (!name) return;
  currentConfigName = name.endsWith(".toml") ? name : name + ".toml";
  $("#config-name").textContent = currentConfigName;
  $("#config-editor").value = '# New config\nexperiment_id = "' + currentConfigName.replace(".toml", "") + '"\nmax_rounds = 3\nopening_message = ""\n\n[[fighters]]\nname = "a"\nprovider = "ollama"\nmodel = "llama3.1:8b"\nsystem_prompt = ""\n\n[[fighters]]\nname = "b"\nprovider = "ollama"\nmodel = "llama3.1:8b"\nsystem_prompt = ""\n\n[judge_llm]\nprovider = "ollama"\nmodel = "llama3.1:8b"\n';
  $("#config-status").textContent = "Unsaved. Click Save.";
});

$("#mode-select").addEventListener("change", (e) => {
  $("#max-parallel-wrap").style.display = e.target.value === "parallel" ? "" : "none";
});

$("#run-config-btn").addEventListener("click", async () => {
  if (!$("#config-editor").value) {
    $("#config-status").textContent = "No config to run.";
    return;
  }
  const commentator = $("#commentator-toggle").checked;
  const language = $("#language-select").value;
  const runs = Math.max(1, parseInt($("#runs-input").value, 10) || 1);
  const parallel = $("#mode-select").value === "parallel";
  const maxParallel = Math.max(1, parseInt($("#max-parallel-input").value, 10) || 3);
  $("#config-status").textContent = "Starting...";
  $$(".tab-btn").forEach((b) => b.classList.remove("active"));
  $$(".tab").forEach((t) => t.classList.remove("active"));
  $('.tab-btn[data-tab="live"]').classList.add("active");
  $("#live").classList.add("active");
  resetLiveView();
  const res = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content: $("#config-editor").value,
      commentator: commentator,
      language: language,
      runs: runs,
      parallel: parallel,
      max_parallel: maxParallel,
    }),
  });
  const data = await res.json();
  if (res.ok) {
    try {
      currentBatchId = data.batch_id;
      currentRunIds = data.run_ids || (data.run_id ? [data.run_id] : []);
      if (!currentRunIds.length) throw new Error("server returned no run_ids");
      selectedRunId = currentRunIds[0];
      $("#config-status").textContent =
        "Started " + currentRunIds.length + " run(s)" + (currentBatchId ? " (batch " + currentBatchId + ")" : "");
      renderRunsList();
      if (selectedRunId) startLiveStream(selectedRunId);
      startRunsPolling();
    } catch (err) {
      $("#live-status").textContent = "UI error: " + err.message;
      $("#config-status").textContent = "UI error: " + err.message;
    }
  } else {
    $("#config-status").textContent = "Error: " + (data.error || res.status);
    $("#live-status").textContent = "Run failed to start.";
  }
});

// --- Live monitor ---
function resetLiveView() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  const toml = $("#config-editor").value || "";
  const m = toml.match(/max_rounds\s*=\s*(\d+)/);
  chartMaxRounds = m ? Math.max(1, parseInt(m[1], 10)) : 5;
  clearLiveView();
}

function clearLiveView() {
  lssHistory = {};
  fighterColors = {};
  $("#event-log").innerHTML = "";
  $("#comment-log").innerHTML = "";
  $("#fighter-log").innerHTML = "";
  $("#chart-legend").innerHTML = "";
  $("#chart-leader").textContent = "No round scores yet.";
  $("#lss-chart").innerHTML = "";
  drawChart();
}

function attachClearButton() {
  const btn = $("#clear-live-btn");
  if (btn && !btn.dataset.bound) {
    btn.dataset.bound = "1";
    btn.addEventListener("click", () => {
      clearAll();
    });
  }
}

async function clearAll() {
  try {
    await fetch("/api/runs/kill", { method: "POST" });
  } catch (e) {}
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  if (runsPollTimer) {
    clearInterval(runsPollTimer);
    runsPollTimer = null;
  }
  currentBatchId = null;
  currentRunIds = [];
  selectedRunId = null;
  $("#runs-panel").style.display = "none";
  $("#runs-list").innerHTML = "";
  clearLiveView();
  $("#live-status").textContent = "Cleared. All background runs killed.";
}

// --- Runs list (multi-run) ---
function renderRunsList() {
  const panel = $("#runs-panel");
  const list = $("#runs-list");
  if (!currentRunIds || currentRunIds.length <= 1) {
    panel.style.display = "none";
    list.innerHTML = "";
    return;
  }
  panel.style.display = "";
  list.innerHTML = "";
  currentRunIds.forEach((rid, idx) => {
    const card = document.createElement("div");
    card.className = "run-card" + (rid === selectedRunId ? " active" : "");
    card.dataset.runId = rid;
    card.innerHTML =
      '<div class="rc-title">Run ' + (idx + 1) + '</div>' +
      '<div class="rc-status" data-status="' + rid + '">starting...</div>' +
      '<div class="rc-winner" data-winner="' + rid + '"></div>';
    card.addEventListener("click", () => selectRun(rid));
    list.appendChild(card);
  });
  updateRunsStatus();
}

async function selectRun(runId) {
  if (runId === selectedRunId && eventSource) return;
  selectedRunId = runId;
  renderRunsList();
  const runInfo = await fetchRunInfo(runId);
  resetLiveView();
  if (runInfo && runInfo.finished) {
    replayFinishedRun(runId);
  } else {
    startLiveStream(runId);
  }
}

async function fetchRunInfo(runId) {
  try {
    const res = await fetch("/api/runs");
    const all = await res.json();
    return all.find((r) => r.run_id === runId) || null;
  } catch (e) {
    return null;
  }
}

function startRunsPolling() {
  if (runsPollTimer) clearInterval(runsPollTimer);
  runsPollTimer = setInterval(updateRunsStatus, 1000);
  updateRunsStatus();
}

async function updateRunsStatus() {
  if (!currentRunIds.length) {
    if (runsPollTimer) { clearInterval(runsPollTimer); runsPollTimer = null; }
    return;
  }
  try {
    const res = await fetch("/api/runs");
    const all = await res.json();
    const byId = {};
    for (const r of all) byId[r.run_id] = r;
    let allFinished = true;
    currentRunIds.forEach((rid, idx) => {
      const info = byId[rid];
      const statusEl = document.querySelector('[data-status="' + rid + '"]');
      const winnerEl = document.querySelector('[data-winner="' + rid + '"]');
      const card = document.querySelector('.run-card[data-run-id="' + rid + '"]');
      if (!info) {
        allFinished = false;
        return;
      }
      if (!info.finished) allFinished = false;
      if (statusEl) {
        statusEl.textContent = info.finished
          ? "finished: " + (info.reason || "unknown")
          : "streaming (" + info.events + " events)";
      }
      if (card) card.classList.toggle("streaming", !info.finished);
      if (winnerEl && info.winner) {
        winnerEl.textContent = "Winner: " + info.winner;
        winnerEl.classList.remove("draw");
      } else if (winnerEl && info.finished && info.reason === "completed") {
        winnerEl.textContent = "Draw";
        winnerEl.classList.add("draw");
      } else if (winnerEl && info.finished) {
        winnerEl.textContent = "no decision";
      }
    });
    if (allFinished && runsPollTimer) {
      clearInterval(runsPollTimer);
      runsPollTimer = null;
    }
  } catch (e) {}
}

function replayFinishedRun(runId) {
  $("#live-status").textContent = "Replaying finished run " + runId;
  eventSource = new EventSource("/api/runs/" + runId + "/stream");
  attachSseHandlers(runId);
}

function attachSseHandlers(runId) {
  eventSource.addEventListener("event", (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === "fighter.response") {
      appendFighterResponse(ev);
    } else {
      appendEvent(ev);
    }
    if (ev.type === "scorekeeper.round_scored") {
      updateChart(ev);
    } else if (ev.type === "referee.decision") {
      showFinalWinner(ev);
    }
  });
  eventSource.addEventListener("comment", (e) => {
    const d = JSON.parse(e.data);
    appendComment(d.text);
  });
  eventSource.addEventListener("finished", (e) => {
    const d = JSON.parse(e.data);
    $("#live-status").textContent = "Finished: " + (d.reason || "unknown");
    if (eventSource) { eventSource.close(); eventSource = null; }
  });
  eventSource.onerror = () => {
    $("#live-status").textContent = "Connection lost.";
  };
}

function startLiveStream(runId) {
  resetLiveView();
  $("#live-status").textContent = "Run " + runId + " — streaming...";
  eventSource = new EventSource("/api/runs/" + runId + "/stream");
  attachSseHandlers(runId);
}

function appendEvent(ev) {
  const log = $("#event-log");
  const div = document.createElement("div");
  div.className = "log-entry " + (ev.source || "");
  const ts = ev.datetime ? ev.datetime.slice(11, 19) : "";
  div.innerHTML =
    '<span class="ts">' + ts + "</span> " +
    '<span class="src">[' + (ev.source || "?") + " R" + ev.round_number + "]</span> " +
    '<span class="type">' + ev.type + "</span>";
  if (ev.type === "scorekeeper.round_scored" && ev.data) {
    const lss = {};
    for (const [f, d] of Object.entries(ev.data.scores || {})) lss[f] = d.lss;
    div.innerHTML += '<div class="content">LSS: ' + JSON.stringify(lss) + "</div>";
  } else if (ev.type === "referee.decision" && ev.data) {
    div.innerHTML += '<div class="content">' + escapeHtml(ev.data.explain || ev.data.action) + "</div>";
  }
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function appendFighterResponse(ev) {
  const log = $("#fighter-log");
  const fighter = (ev.data && ev.data.fighter) || ev.source || "?";
  const div = document.createElement("div");
  div.className = "fight-msg " + fighter;
  const who = document.createElement("div");
  who.className = "who";
  who.textContent = fighter + " \u00b7 Round " + ev.round_number;
  const body = document.createElement("div");
  body.className = "body";
  body.textContent = (ev.data && ev.data.content) || "(empty)";
  div.appendChild(who);
  div.appendChild(body);
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function appendComment(text) {
  const log = $("#comment-log");
  const div = document.createElement("div");
  div.className = "comment";
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

// --- LSS chart ---
function updateChart(ev) {
  const scores = (ev.data && ev.data.scores) || {};
  const round = ev.round_number;
  const names = Object.keys(scores);
  if (names.length === 0) return;
  if (Object.keys(fighterColors).length === 0) {
    names.forEach((n, i) => { fighterColors[n] = COLOR_PALETTE[i % COLOR_PALETTE.length]; });
    buildLegend();
  }
  for (const name of names) {
    if (!lssHistory[name]) lssHistory[name] = [];
    lssHistory[name][round - 1] = scores[name].lss;
  }
  drawChart();
  updateLeader(round);
}

function buildLegend() {
  const el = $("#chart-legend");
  el.innerHTML = "";
  for (const [name, color] of Object.entries(fighterColors)) {
    const span = document.createElement("span");
    span.className = "legend-item";
    const dot = document.createElement("span");
    dot.className = "legend-dot";
    dot.style.background = color;
    span.appendChild(dot);
    span.appendChild(document.createTextNode(name));
    el.appendChild(span);
  }
}

function lastDefined(arr) {
  for (let i = arr.length - 1; i >= 0; i--) {
    if (arr[i] !== undefined) return arr[i];
  }
  return undefined;
}

function currentLeader() {
  const names = Object.keys(lssHistory);
  if (names.length !== 2) return null;
  const [a, b] = names;
  const va = lastDefined(lssHistory[a]);
  const vb = lastDefined(lssHistory[b]);
  if (va === undefined || vb === undefined) return null;
  if (va > vb) return { name: a, va, vb, diff: va - vb };
  if (vb > va) return { name: b, va: vb, vb: va, diff: vb - va };
  return { name: null, va, vb, diff: 0 };
}

function updateLeader(round) {
  const lead = currentLeader();
  const el = $("#chart-leader");
  if (!lead) {
    el.textContent = "Round " + round + ": waiting for both scores...";
    return;
  }
  if (lead.name === null) {
    el.innerHTML = "Round " + round + ': tied at <span class="lead-name">' + lead.va.toFixed(2) + "</span>";
    return;
  }
  const color = fighterColors[lead.name] || "#7ec";
  el.innerHTML =
    "Round " + round + ': <span class="lead-name" style="color:' + color + '">' +
    escapeHtml(lead.name) + "</span> leads — " +
    lead.va.toFixed(2) + " vs " + lead.vb.toFixed(2) + " (+" + lead.diff.toFixed(2) + ")";
}

function showFinalWinner(ev) {
  const d = ev.data || {};
  const el = $("#chart-leader");
  if (d.winner) {
    const color = fighterColors[d.winner] || "#7ec";
    el.innerHTML =
      'Winner: <span class="lead-name" style="color:' + color + '">' +
      escapeHtml(d.winner) + "</span> (" + escapeHtml(d.action || "") + ")";
  } else {
    el.textContent = "Result: " + (d.action || "unknown");
  }
}

function drawChart() {
  const svg = $("#lss-chart");
  const W = 600, H = 240;
  const pad = { l: 38, r: 14, t: 12, b: 26 };
  const plotW = W - pad.l - pad.r;
  const plotH = H - pad.t - pad.b;
  const xMax = chartMaxRounds;
  const xScale = (r) => pad.l + (r / xMax) * plotW;
  const yScale = (v) => pad.t + (1 - v) * plotH;
  let s = "";
  for (const v of [0, 0.25, 0.5, 0.75, 1.0]) {
    const y = yScale(v);
    s += '<line x1="' + pad.l + '" y1="' + y + '" x2="' + (W - pad.r) + '" y2="' + y + '" stroke="#161a23" stroke-width="1"/>';
    s += '<text x="' + (pad.l - 5) + '" y="' + (y + 3) + '" text-anchor="end" fill="#567" font-size="10" font-family="monospace">' + v.toFixed(2) + "</text>";
  }
  for (let r = 0; r <= xMax; r++) {
    const x = xScale(r);
    s += '<text x="' + x + '" y="' + (H - pad.b + 16) + '" text-anchor="middle" fill="#567" font-size="10" font-family="monospace">' + r + "</text>";
  }
  s += '<line x1="' + pad.l + '" y1="' + pad.t + '" x2="' + pad.l + '" y2="' + (H - pad.b) + '" stroke="#2a2f3a" stroke-width="1"/>';
  s += '<line x1="' + pad.l + '" y1="' + (H - pad.b) + '" x2="' + (W - pad.r) + '" y2="' + (H - pad.b) + '" stroke="#2a2f3a" stroke-width="1"/>';
  const lead = currentLeader();
  const leaderName = lead ? lead.name : null;
  for (const [name, scores] of Object.entries(lssHistory)) {
    const color = fighterColors[name] || "#888";
    const isLeader = name === leaderName;
    const sw = isLeader ? 3 : 2;
    const pts = [];
    scores.forEach((v, i) => {
      if (v !== undefined) pts.push(xScale(i + 1) + "," + yScale(v));
    });
    if (pts.length > 1) {
      s += '<polyline points="' + pts.join(" ") + '" fill="none" stroke="' + color + '" stroke-width="' + sw + '" stroke-linejoin="round" stroke-linecap="round"/>';
    }
    for (const p of pts) {
      const [px, py] = p.split(",");
      s += '<circle cx="' + px + '" cy="' + py + '" r="' + (isLeader ? 4 : 3) + '" fill="' + color + '"/>';
    }
  }
  s += '<text x="' + (pad.l + plotW / 2) + '" y="' + (H - 2) + '" text-anchor="middle" fill="#789" font-size="10">Round</text>';
  svg.innerHTML = s;
}

// --- Results ---
async function loadExperiments() {
  const res = await fetch("/api/experiments");
  const exps = await res.json();
  const list = $("#experiment-list");
  list.innerHTML = "";
  for (const e of exps) {
    const li = document.createElement("li");
    li.textContent = e.experiment_id;
    li.addEventListener("click", () => loadExperimentDetail(e.experiment_id, li));
    list.appendChild(li);
  }
}

async function loadExperimentDetail(expId, li) {
  $$("#experiment-list li").forEach((x) => x.classList.remove("active"));
  if (li) li.classList.add("active");
  const res = await fetch("/api/experiments/" + expId);
  const data = await res.json();
  const d = $("#experiment-detail");
  const winner = data.winner;
  const action = data.decision ? data.decision.action : "none";
  const cls = action === "draw" ? "draw" : winner ? "win" : "none";
  const winnerText = winner
    ? "Winner: " + winner + " (" + action + ")"
    : action === "draw"
    ? "Draw (" + action + ")"
    : "No decision (" + action + ")";
  let html = '<div class="winner-box ' + cls + '">' + escapeHtml(winnerText) + "</div>";
  html += '<div class="detail-section"><h3>Settings</h3><table>';
  html += row("experiment_id", data.meta.experiment_id);
  html += row("max_rounds", data.meta.max_rounds);
  html += row("opening_message", data.meta.opening_message);
  for (const f of data.meta.fighters || []) {
    html += row("fighter", f.name + " (" + f.model + ", T=" + f.temperature + ")");
  }
  html += row("judge_llm", (data.meta.judge_llm || {}).model);
  html += row("commentator", (data.meta.commentator || {}).enabled ? "enabled" : "disabled");
  html += row("referee threshold", (data.meta.referee || {}).lss_critical_threshold);
  html += "</table></div>";
  html += '<div class="detail-section"><h3>Events (' + data.event_count + ')</h3><div class="log">';
  for (const ev of data.events) {
    html +=
      '<div class="log-entry ' + (ev.source || "") + '">' +
      '<span class="type">' + ev.type + "</span> " +
      '<span class="src">[' + (ev.source || "?") + " R" + ev.round_number + "]</span>";
    if (ev.type === "referee.decision" && ev.data) {
      html += '<div class="content">' + escapeHtml(ev.data.explain || "") + "</div>";
    } else if (ev.type === "scorekeeper.round_scored" && ev.data) {
      const lss = {};
      for (const [f, dd] of Object.entries(ev.data.scores || {})) lss[f] = dd.lss;
      html += '<div class="content">LSS: ' + JSON.stringify(lss) + "</div>";
    }
    html += "</div>";
  }
  html += "</div></div>";
  d.innerHTML = html;
}

function row(key, val) {
  return "<tr><td>" + escapeHtml(String(key)) + "</td><td>" + escapeHtml(String(val)) + "</td></tr>";
}

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// --- Init ---
async function loadLanguages() {
  try {
    const res = await fetch("/api/languages");
    const langs = await res.json();
    const sel = $("#language-select");
    for (const l of langs) {
      const opt = document.createElement("option");
      opt.value = l.code;
      opt.textContent = l.name;
      sel.appendChild(opt);
    }
  } catch (e) {
    const opt = document.createElement("option");
    opt.value = "en";
    opt.textContent = "English";
    $("#language-select").appendChild(opt);
  }
}

async function loadKeyStatus() {
  try {
    const res = await fetch("/api/keys");
    const status = await res.json();
    for (const [provider, set] of Object.entries(status)) {
      const el = $("#key-status-" + provider);
      if (el) {
        el.textContent = set ? "configured" : "not set";
        el.classList.toggle("set", set);
      }
    }
  } catch (e) {}
}

$("#save-keys-btn").addEventListener("click", async () => {
  const body = {};
  const openai = $("#key-openai").value.trim();
  const anthropic = $("#key-anthropic").value.trim();
  if (openai) body.OPENAI_API_KEY = openai;
  if (anthropic) body.ANTHROPIC_API_KEY = anthropic;
  if (!Object.keys(body).length) {
    $("#keys-saved-status").textContent = "Enter a key first.";
    return;
  }
  const res = await fetch("/api/keys", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const status = await res.json();
  for (const [provider, set] of Object.entries(status)) {
    const el = $("#key-status-" + provider);
    if (el) {
      el.textContent = set ? "configured" : "not set";
      el.classList.toggle("set", set);
    }
  }
  $("#key-openai").value = "";
  $("#key-anthropic").value = "";
  $("#keys-saved-status").textContent = "Saved to secrets.json";
});

$$("[data-clear]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const provider = btn.dataset.clear;
    const res = await fetch("/api/keys/" + provider, { method: "DELETE" });
    const status = await res.json();
    for (const [p, set] of Object.entries(status)) {
      const el = $("#key-status-" + p);
      if (el) {
        el.textContent = set ? "configured" : "not set";
        el.classList.toggle("set", set);
      }
    }
  });
});

loadLanguages();
loadConfigs();
loadKeyStatus();
attachClearButton();
drawChart();
