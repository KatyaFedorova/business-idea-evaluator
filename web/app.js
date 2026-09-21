/* Business Idea Evaluator -- front-end.
   Talks to the FastAPI backend: POST /api/evaluate (JSON) and POST /api/chat (streamed text).
   Add ?demo=1 to the URL to render a canned report with no API key and no backend. */

const $ = (id) => document.getElementById(id);
const DEMO = new URLSearchParams(location.search).has("demo");

const state = { evaluation: null, idea: "", history: [] };

const SAMPLE =
  "A subscription iOS app for people who doomscroll. It watches TikTok and Instagram usage " +
  "with Apple's Screen Time APIs and, once you pass your daily limit, plays a recording of " +
  "your own voice shaming you until you close the app. $4.99/month, aimed at 20-35 year olds " +
  "who have already tried and abandoned three screen-time blockers.";

/* ---------- rendering ---------- */
function show(id, visible) {
  $(id).classList.toggle("hidden", !visible);
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

const DIM_LABELS = {
  problem_severity: "Problem severity",
  market_size: "Market size",
  differentiation: "Differentiation",
  feasibility: "Feasibility",
  monetization: "Monetization",
};

function renderReport(result) {
  const e = result.evaluation;
  state.evaluation = e;

  $("verdictText").textContent = e.verdict.toUpperCase();
  $("verdictBox").className = "verdict verdict-" + e.verdict;
  $("overallScore").textContent = e.overall_score;
  $("headline").textContent = e.headline;

  $("dimensionRows").innerHTML = e.dimensions
    .map(
      (d) => `<tr>
        <td><b>${esc(DIM_LABELS[d.name] || d.name)}</b></td>
        <td>${d.score}/10 <div class="meter"><i style="width:${d.score * 10}%"></i></div></td>
        <td>${esc(d.rationale)}</td>
      </tr>`
    )
    .join("");

  $("targetCustomer").textContent = e.target_customer;
  $("riskiestAssumption").textContent = e.riskiest_assumption;
  $("firstExperiment").textContent = e.first_experiment;
  $("comparables").textContent = (e.comparable_companies || []).join(", ") || "none named";

  $("riskRows").innerHTML = e.risks
    .map(
      (r) => `<tr>
        <td><b>${esc(r.title)}</b></td>
        <td class="sev-${esc(r.severity)}">${esc(r.severity.toUpperCase())}</td>
        <td>${esc(r.mitigation)}</td>
      </tr>`
    )
    .join("");

  const u = result.usage || {};
  $("runStats").textContent =
    `model: ${u.model || "?"}  |  prompt: ${result.prompt_version || "?"}  |  ` +
    `${u.input_tokens || 0} in / ${u.output_tokens || 0} out tokens  |  ` +
    `${((u.latency_ms || 0) / 1000).toFixed(1)}s  |  $${(u.cost_usd || 0).toFixed(4)}`;

  show("report", true);
  show("chatBox", true);
}

/* ---------- evaluate ---------- */
let timer = null;
function startTimer() {
  const t0 = Date.now();
  $("elapsed").textContent = "0.0s";
  timer = setInterval(() => {
    $("elapsed").textContent = ((Date.now() - t0) / 1000).toFixed(1) + "s";
  }, 100);
}
function stopTimer() {
  if (timer) clearInterval(timer);
  timer = null;
}

async function evaluate() {
  const idea = $("idea").value.trim();
  if (idea.length < 15) {
    fail("Please describe the idea in at least a sentence or two.");
    return;
  }
  state.idea = idea;
  state.history = [];
  $("transcript").innerHTML = "";
  show("error", false);
  show("report", false);
  show("chatBox", false);
  show("loading", true);
  $("evaluateBtn").disabled = true;
  startTimer();

  try {
    const result = DEMO ? await demoResult(idea) : await postEvaluate(idea);
    renderReport(result);
  } catch (err) {
    fail(err.message || String(err));
  } finally {
    stopTimer();
    show("loading", false);
    $("evaluateBtn").disabled = false;
  }
}

async function postEvaluate(idea) {
  const res = await fetch("/api/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idea }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Server said ${res.status}: ${detail.slice(0, 300)}`);
  }
  return res.json();
}

function fail(msg) {
  $("errorText").textContent = msg;
  show("error", true);
}

/* ---------- chat ---------- */
async function send() {
  const text = $("chatInput").value.trim();
  if (!text) return;
  $("chatInput").value = "";
  addMessage("user", text);
  state.history.push({ role: "user", content: text });

  const bubble = addMessage("bot", "");
  $("sendBtn").disabled = true;

  try {
    if (DEMO) {
      await typeInto(bubble, "Demo mode: start the backend (uvicorn) to chat with Claude.");
    } else {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          idea: state.idea,
          evaluation: state.evaluation,
          messages: state.history,
        }),
      });
      if (!res.ok) throw new Error(`Server said ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let acc = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        acc += decoder.decode(value, { stream: true });
        bubble.textContent = acc;
        $("transcript").scrollTop = $("transcript").scrollHeight;
      }
    }
    state.history.push({ role: "assistant", content: bubble.textContent });
  } catch (err) {
    bubble.textContent = "[error] " + (err.message || err);
  } finally {
    $("sendBtn").disabled = false;
    $("chatInput").focus();
  }
}

function addMessage(who, text) {
  const wrap = document.createElement("p");
  wrap.className = "msg " + who;
  wrap.innerHTML = `<span class="who">${who === "user" ? "YOU" : "THE ANALYST"}:</span> `;
  const body = document.createElement("span");
  body.className = "body";
  body.textContent = text;
  wrap.appendChild(body);
  $("transcript").appendChild(wrap);
  $("transcript").scrollTop = $("transcript").scrollHeight;
  return body;
}

async function typeInto(el, text) {
  for (const ch of text) {
    el.textContent += ch;
    await new Promise((r) => setTimeout(r, 12));
  }
}

/* ---------- demo data (no API key needed) ---------- */
async function demoResult(idea) {
  await new Promise((r) => setTimeout(r, 900));
  return {
    idea,
    prompt_version: "demo",
    evaluation: {
      headline: "Sharp hook, thin moat, and the platform owns your distribution.",
      verdict: "refine",
      overall_score: 54,
      dimensions: [
        { name: "problem_severity", score: 8, rationale: "Doomscrolling regret is widely felt and people already pay to fix it." },
        { name: "market_size", score: 6, rationale: "Screen-time tooling is a real but crowded consumer niche with low willingness to pay." },
        { name: "differentiation", score: 7, rationale: "Self-recorded shaming audio is memorable and hard to copy emotionally, easy to copy technically." },
        { name: "feasibility", score: 4, rationale: "iOS will not let a background extension talk over another app; the core promise is platform-limited." },
        { name: "monetization", score: 5, rationale: "$4.99/month is plausible but churn is brutal once the novelty wears off." },
      ],
      target_customer: "20-35 year olds who have already abandoned three screen-time blockers.",
      riskiest_assumption: "That the shaming audio can reach the user at the moment of scrolling, rather than after.",
      risks: [
        { title: "Platform restriction", severity: "high", mitigation: "Design around notifications and re-entry audio; validate with a TestFlight build before building billing." },
        { title: "Novelty churn", severity: "high", mitigation: "Measure week-4 retention in a 200-user cohort before any paid acquisition." },
        { title: "Trivial to clone", severity: "medium", mitigation: "Build the voice library and streak data into a switching cost." },
      ],
      first_experiment: "Ship a free TestFlight build to 100 users and measure day-14 retention before writing a payment screen.",
      comparable_companies: ["Opal", "one sec", "Freedom", "Forest"],
    },
    usage: { model: "demo", input_tokens: 0, output_tokens: 0, latency_ms: 900, cost_usd: 0 },
  };
}

/* ---------- wiring ---------- */
$("evaluateBtn").addEventListener("click", evaluate);
$("sampleBtn").addEventListener("click", () => { $("idea").value = SAMPLE; });
$("clearBtn").addEventListener("click", () => {
  $("idea").value = "";
  show("report", false);
  show("chatBox", false);
  show("error", false);
});
$("sendBtn").addEventListener("click", send);
$("chatInput").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
if (DEMO) $("runStats").textContent = "demo mode";

/* ?demo=1&auto=1 renders a full report on load -- used for screenshots and the docs page. */
if (DEMO && new URLSearchParams(location.search).has("auto")) {
  $("idea").value = SAMPLE;
  evaluate();
}

/* Sparkle cursor trail. Peak 1999, and the one effect the page would be poorer without. */
(function sparkleTrail() {
  const COLORS = ["#ff3399", "#ffee00", "#00ccff", "#33cc33", "#9933ff"];
  let last = 0;
  document.addEventListener("mousemove", (e) => {
    const now = Date.now();
    if (now - last < 45) return; // don't carpet the page
    last = now;
    const s = document.createElement("span");
    s.className = "sparkle";
    s.textContent = "✦";
    s.style.left = e.pageX + "px";
    s.style.top = e.pageY + "px";
    s.style.color = COLORS[Math.floor(Math.random() * COLORS.length)];
    document.body.appendChild(s);
    setTimeout(() => s.remove(), 700);
  });
})();
