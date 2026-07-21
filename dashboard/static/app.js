const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let currentConfigName = null;
let eventSource = null;

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

$("#run-config-btn").addEventListener("click", async () => {
  if (!$("#config-editor").value) {
    $("#config-status").textContent = "No config to run.";
    return;
  }
  const commentator = $("#commentator-toggle").checked;
  const language = $("#language-select").value;
  $("#config-status").textContent = "Starting...";
  const res = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content: $("#config-editor").value,
      commentator: commentator,
      language: language,
    }),
  });
  const data = await res.json();
  if (res.ok) {
    $("#config-status").textContent = "Started run: " + data.run_id;
    $$(".tab-btn").forEach((b) => b.classList.remove("active"));
    $$(".tab").forEach((t) => t.classList.remove("active"));
    $('.tab-btn[data-tab="live"]').classList.add("active");
    $("#live").classList.add("active");
    startLiveStream(data.run_id);
  } else {
    $("#config-status").textContent = "Error: " + data.error;
  }
});

// --- Live monitor ---
function startLiveStream(runId) {
  if (eventSource) eventSource.close();
  $("#event-log").innerHTML = "";
  $("#comment-log").innerHTML = "";
  $("#fighter-log").innerHTML = "";
  $("#live-status").textContent = "Run " + runId + " — streaming...";
  eventSource = new EventSource("/api/runs/" + runId + "/stream");
  eventSource.addEventListener("event", (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === "fighter.response") {
      appendFighterResponse(ev);
    } else {
      appendEvent(ev);
    }
  });
  eventSource.addEventListener("comment", (e) => {
    const d = JSON.parse(e.data);
    appendComment(d.text);
  });
  eventSource.addEventListener("finished", (e) => {
    const d = JSON.parse(e.data);
    $("#live-status").textContent = "Finished: " + (d.reason || "unknown");
    eventSource.close();
    eventSource = null;
  });
  eventSource.onerror = () => {
    $("#live-status").textContent = "Connection lost.";
  };
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
