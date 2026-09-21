/* Session state: pure functions over a plain object, so they can be tested
   without a browser. app.js owns the DOM and IndexedDB; this file owns the shape. */

export const SESSION_VERSION = 1;

export function newSession(idea = "") {
  return {
    version: SESSION_VERSION,
    id: `s_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    createdAt: new Date().toISOString(),
    idea,
    rounds: [],
    attachments: [],
    revisions: [],
    totalCostUsd: 0,
  };
}

export function appendRound(session, round) {
  return {
    ...session,
    rounds: [...session.rounds, round],
    totalCostUsd: round.cost_usd ? session.totalCostUsd + round.cost_usd : session.totalCostUsd,
  };
}

export function reviseIdea(session, idea) {
  const next = (idea || "").trim();
  if (!next || next === session.idea) return session;
  const revision = { at: new Date().toISOString(), previous: session.idea, current: next };
  return { ...session, idea: next, revisions: [...session.revisions, revision] };
}

export function addAttachments(session, attachments) {
  return { ...session, attachments: [...session.attachments, ...attachments] };
}

export function removeAttachment(session, id) {
  return { ...session, attachments: session.attachments.filter((a) => a.id !== id) };
}

export function fileIds(session) {
  return session.attachments.map((a) => a.file_id).filter(Boolean);
}

/** What the founder may do next, derived from the rounds so far. */
export function phase(session) {
  if (session.rounds.length === 0) return "empty";
  return session.rounds[session.rounds.length - 1].kind;
}

export function reaskCount(session) {
  return session.rounds.filter((r) => r.kind === "reask").length;
}

export function canAnswer(session) {
  const p = phase(session);
  return p === "questions" || p === "reask" || p === "verdict";
}

export function lastReport(session) {
  for (let i = session.rounds.length - 1; i >= 0; i -= 1) {
    if (session.rounds[i].report) return session.rounds[i].report;
  }
  return null;
}

/** The transcript the stateless API needs: rounds plus the idea, nothing else. */
export function verdictPayload(session, answers) {
  return {
    idea: session.idea,
    rounds: session.rounds.map((r) => ({
      index: r.index,
      kind: r.kind,
      submission: r.submission || [],
      questions: r.questions || null,
      report: r.report || null,
    })),
    answers,
    attachments: session.attachments,
    spent: session.totalCostUsd,
  };
}
