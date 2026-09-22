/* Business Idea Evaluator -- front end.

   Two panes: the idea on the left, the conversation on the right. The server keeps
   nothing, so this file owns the session and stores it in IndexedDB. */

import {
  addAttachments,
  appendRound,
  canAnswer,
  fileIds,
  lastReport,
  newSession,
  phase,
  removeAttachment,
  reviseIdea,
  verdictPayload,
} from "./session.js";

const $ = (id) => document.getElementById(id);
const DB_NAME = "bie";
const STORE = "sessions";
const KEY = "current";

let session = newSession();
let limits = null;
let busy = false;
let lastAttempt = null;
let timer = null;

/* ----------------------------- storage ----------------------------- */
function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function save() {
  try {
    const db = await openDb();
    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).put(session, KEY);
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    /* A session that cannot be stored is still a usable session. */
  }
}

async function restore() {
  try {
    const db = await openDb();
    const stored = await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readonly");
      const get = tx.objectStore(STORE).get(KEY);
      get.onsuccess = () => resolve(get.result);
      get.onerror = () => reject(get.error);
    });
    if (stored && stored.rounds) session = stored;
  } catch {
    /* ignore */
  }
}

/* ----------------------------- rendering ----------------------------- */
function esc(value) {
  const d = document.createElement("div");
  d.textContent = value == null ? "" : String(value);
  return d.innerHTML;
}

function money(value) {
  return `$${Number(value || 0).toFixed(4)}`;
}

function turn(who, bodyHtml, extraClass = "") {
  const wrap = document.createElement("div");
  wrap.className = `msg ${extraClass}`.trim();
  wrap.innerHTML = `<div class="who">${esc(who)}</div><div class="body">${bodyHtml}</div>`;
  return wrap;
}

function questionsHtml(round) {
  const note = round.questions.note
    ? `<div class="reask-note">${esc(round.questions.note)}</div>`
    : "";
  const items = round.questions.questions
    .map((q) => `<li>${esc(q.text)}</li>`)
    .join("");
  return `${note}<ol class="qlist">${items}</ol>
    <div class="cost">${esc(round.usage ? round.usage.model : "")} &middot; ${money(round.cost_usd)}</div>`;
}

function verdictLine(report) {
  if (report.verdict === "PROCEED_ONLY_AFTER_TESTING") {
    return `PROCEED ONLY AFTER TESTING ${report.verdict_condition || ""}`.trim();
  }
  return report.verdict === "DONT_PROCEED" ? "DON'T PROCEED" : "PROCEED";
}

function list(items) {
  return `<ul>${items.map((i) => `<li>${i}</li>`).join("")}</ul>`;
}

function reportHtml(round) {
  const r = round.report;
  const fails = [...r.fails_because]
    .sort((a, b) => a.rank - b.rank)
    .map((f) => `${esc(f.text)}${f.is_guess ? ' <span class="guess">(guess)</span>' : ""}`);
  const plan = r.validation_plan;
  const research = r.research_directions.map((d) => {
    const who = d.competitor ? ` <b>${esc(d.competitor)}</b>` : "";
    const what = d.what_to_check ? ` &mdash; ${esc(d.what_to_check)}` : "";
    return `${esc(d.question)}${who} <span class="small">(${esc(d.where_to_look)})</span>${what}`;
  });

  const sources = round.sources && round.sources.length
    ? `<h4>Sources</h4><div class="sources">${round.sources
        .map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title || s.url)}</a>`)
        .join("<br>")}</div>`
    : "";
  const degraded = round.research_status !== "ok"
    ? `<div class="degraded">Research was ${esc(round.research_status)} for this round, so any
       claim without a source above is unverified.</div>`
    : "";
  const contradictions = r.contradictions.length
    ? `<h4>Contradictions in your answers</h4>${list(r.contradictions.map(esc))}`
    : "";
  const priorArt = r.prior_art.length
    ? `<h4>This already exists as</h4>${list(r.prior_art.map(esc))}`
    : "";
  const missing = r.missing_data.length
    ? `<h4>Data neither of us has</h4>${list(r.missing_data.map(esc))}`
    : "";

  return `<div class="report">
    <div class="verdict-line">${esc(verdictLine(r))}</div>
    <div><b>Confidence:</b> ${esc(r.confidence)} &mdash; ${esc(r.confidence_movers)}</div>
    <h4>Works because</h4>${list(r.works_because.map(esc))}
    <h4>Fails because</h4><ol class="qlist">${fails.map((f) => `<li>${f}</li>`).join("")}</ol>
    <h4>Riskiest assumption</h4><div>${esc(r.riskiest_assumption)}</div>
    <h4>Validation plan (${esc(plan.duration_days)} days, no code)</h4>
    ${list(plan.steps.map(esc))}
    <div><b>Talk to:</b> ${esc(plan.who_to_talk_to)}</div>
    <div><b>Pass:</b> ${esc(plan.pass_threshold)}</div>
    <div><b>Fail:</b> ${esc(plan.fail_threshold)}</div>
    <h4>Research to do</h4>${list(research)}
    <h4>Kill criteria</h4>${list(r.kill_criteria.map(esc))}
    ${contradictions}${priorArt}${missing}${sources}${degraded}
    <div class="cost">${esc(round.usage ? round.usage.model : "")} &middot; ${money(round.cost_usd)}</div>
  </div>`;
}

function render() {
  const transcript = $("transcript");
  transcript.innerHTML = "";

  session.rounds.forEach((round) => {
    (round.submission || []).forEach((message) => {
      if (message.text && message.text.trim()) {
        transcript.appendChild(turn("YOU", esc(message.text).replace(/\n/g, "<br>"), "user"));
      }
      (message.attachment_ids || []).forEach((id) => {
        const found = session.attachments.find((a) => a.id === id);
        if (found) {
          transcript.appendChild(
            turn("YOU", `<i>attached ${esc(found.filename)}</i>`, "user")
          );
        }
      });
    });
    if (round.questions) {
      transcript.appendChild(turn("EVALUATOR", questionsHtml(round), "bot evaluator"));
    }
    if (round.report) {
      transcript.appendChild(turn("EVALUATOR", reportHtml(round), "bot evaluator"));
    }
  });

  session.revisions.forEach((rev) => {
    transcript.appendChild(
      turn("SYSTEM", `You revised the idea: ${esc(rev.current)}`, "system")
    );
  });

  transcript.scrollTop = transcript.scrollHeight;

  const started = session.rounds.length > 0;
  $("startBtn").disabled = busy || started;
  $("reviseBtn").classList.toggle("hidden", !started);
  $("sendBtn").disabled = busy || !canAnswer(session);
  $("verdictBtn").disabled = busy || !canAnswer(session);
  $("copyBtn").classList.toggle("hidden", !lastReport(session));
  $("runStats").textContent = started
    ? `${session.rounds.length} round(s) · ${money(session.totalCostUsd)} this session`
    : " ";
  renderAttachments();
}

function renderAttachments() {
  const list = $("attachList");
  list.innerHTML = "";
  session.attachments.forEach((a) => {
    const li = document.createElement("li");
    const state = a.readable ? "" : ` — could not be read: ${a.error || "unknown"}`;
    li.innerHTML = `${esc(a.filename)} <span class="small">(${Math.round(a.size_bytes / 1024)} KB)${esc(state)}</span>`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "x";
    remove.onclick = async () => {
      session = removeAttachment(session, a.id);
      await save();
      render();
    };
    li.appendChild(remove);
    list.appendChild(li);
  });
}

/* ----------------------------- plumbing ----------------------------- */
function setBusy(on, what = "Thinking…") {
  busy = on;
  $("waiting").classList.toggle("hidden", !on);
  $("waitingText").textContent = what;
  if (on) {
    const start = Date.now();
    timer = setInterval(() => {
      $("elapsed").textContent = `${((Date.now() - start) / 1000).toFixed(1)}s`;
    }, 100);
  } else if (timer) {
    clearInterval(timer);
    timer = null;
  }
  render();
}

function showError(message, retryable) {
  $("errorText").textContent = message;
  $("errorBox").classList.remove("hidden");
  $("retryBtn").classList.toggle("hidden", !retryable);
}

function clearError() {
  $("errorBox").classList.add("hidden");
}

async function post(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (payload && payload.error) || {
      message: "Something went wrong. Try again.",
      retryable: true,
    };
    const failure = new Error(error.message);
    failure.retryable = error.retryable;
    throw failure;
  }
  return payload;
}

function roundFrom(payload, index, submission) {
  return {
    index,
    kind: payload.kind,
    submission,
    questions: payload.questions || null,
    report: payload.report || null,
    sources: payload.sources || [],
    research_status: payload.research_status || "unavailable",
    usage: payload.usage || null,
    cost_usd: payload.cost_usd || 0,
  };
}

/* ----------------------------- actions ----------------------------- */
async function start() {
  const idea = $("idea").value.trim();
  if (limits && idea.length < limits.min_idea_chars) {
    showError(`Tell us a bit more — at least ${limits.min_idea_chars} characters.`, false);
    return;
  }
  clearError();
  session = { ...session, idea };
  lastAttempt = start;
  setBusy(true, "Reading your idea…");
  try {
    const payload = await post("/api/questions", {
      idea,
      attachments: session.attachments,
    });
    const round = roundFrom(payload, 0, [
      { text: idea, attachment_ids: session.attachments.map((a) => a.id) },
    ]);
    session = appendRound(session, round);
    await save();
    clearError();
  } catch (error) {
    showError(error.message, error.retryable !== false);
  } finally {
    setBusy(false);
  }
}

async function send(forVerdict) {
  const text = $("answer").value.trim();
  if (!text && !forVerdict) return;
  clearError();
  lastAttempt = () => send(forVerdict);
  const pending = session.attachments
    .filter((a) => !session.rounds.some((r) => (r.submission || []).some((m) => (m.attachment_ids || []).includes(a.id))))
    .map((a) => a.id);
  const answers = [{ text, attachment_ids: pending }];
  setBusy(true, "Researching and thinking…");
  try {
    const payload = await post("/api/verdict", verdictPayload(session, answers));
    session = appendRound(session, roundFrom(payload, session.rounds.length, answers));
    $("answer").value = "";
    await save();
  } catch (error) {
    showError(error.message, error.retryable !== false);
  } finally {
    setBusy(false);
  }
}

async function uploadFiles(files) {
  if (!files.length) return;
  clearError();
  const form = new FormData();
  [...files].forEach((file) => form.append("files", file));
  setBusy(true, "Reading your files…");
  try {
    const response = await fetch("/api/attachments", { method: "POST", body: form });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const error = (payload && payload.error) || { message: "That file was not accepted." };
      showError(error.message, false);
      return;
    }
    session = addAttachments(session, payload.attachments);
    const unreadable = payload.attachments.filter((a) => !a.readable);
    if (unreadable.length) {
      showError(
        `Could not read ${unreadable.map((a) => a.filename).join(", ")}. Send without them, or remove and try again.`,
        false
      );
    }
    await save();
  } finally {
    setBusy(false);
    $("fileInput").value = "";
  }
}

async function clearSession() {
  const ids = fileIds(session);
  if (ids.length) {
    fetch("/api/attachments", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_ids: ids }),
    }).catch(() => {});
  }
  session = newSession();
  $("idea").value = "";
  $("answer").value = "";
  clearError();
  await save();
  render();
}

function copyReport() {
  const report = lastReport(session);
  if (!report) return;
  const text = $("transcript").querySelector(".report").innerText;
  navigator.clipboard.writeText(text).then(
    () => ($("runStats").textContent = "Report copied to the clipboard."),
    () => showError("Could not copy. Select the report and copy manually.", false)
  );
}

/* ----------------------------- wiring ----------------------------- */
async function init() {
  try {
    limits = await (await fetch("/api/limits")).json();
  } catch {
    /* the page still works; the server will enforce the limits anyway */
  }

  await restore();
  if (session.idea) $("idea").value = session.idea;

  $("startBtn").onclick = start;
  $("sendBtn").onclick = () => send(false);
  $("verdictBtn").onclick = () => send(true);
  $("clearBtn").onclick = clearSession;
  $("copyBtn").onclick = copyReport;
  $("retryBtn").onclick = () => lastAttempt && lastAttempt();
  $("fileInput").onchange = (event) => uploadFiles(event.target.files);
  $("reviseBtn").onclick = async () => {
    session = reviseIdea(session, $("idea").value);
    await save();
    render();
  };
  $("answer").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) send(false);
  });

  render();
}

init();
export { phase };
