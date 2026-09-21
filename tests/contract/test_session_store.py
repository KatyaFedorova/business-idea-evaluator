"""T048 — the browser session's pure logic, exercised under node.

web/session.js holds the shape of a session so it can be tested without a browser;
web/app.js keeps the DOM and IndexedDB parts that cannot be.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
SESSION_JS = Path(__file__).resolve().parents[2] / "web" / "session.js"

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

SCRIPT_TEMPLATE = """
import {
  newSession, appendRound, reviseIdea, addAttachments, removeAttachment,
  fileIds, phase, reaskCount, canAnswer, lastReport, verdictPayload,
} from "__SESSION_JS__";

const out = {};
let s = newSession("an idea");
out.emptyPhase = phase(s);
out.cannotAnswerYet = canAnswer(s);

s = appendRound(s, { index: 0, kind: "questions", cost_usd: 0.10, questions: { questions: [] } });
out.afterQuestions = phase(s);
out.canAnswerNow = canAnswer(s);

s = appendRound(s, { index: 1, kind: "reask", cost_usd: 0.20, questions: { note: "vague" } });
s = appendRound(s, { index: 2, kind: "verdict", cost_usd: 0.30, report: { verdict: "PROCEED" } });
out.total = s.totalCostUsd;
out.reasks = reaskCount(s);
out.lastVerdict = lastReport(s).verdict;

s = reviseIdea(s, "a revised idea");
out.idea = s.idea;
out.revisions = s.revisions.length;
out.noRevisionForTheSameText = reviseIdea(s, "a revised idea").revisions.length;
out.noRevisionForEmpty = reviseIdea(s, "   ").revisions.length;

s = addAttachments(s, [
  { id: "a1", filename: "n.xlsx", file_id: "file_1" },
  { id: "a2", filename: "s.png", file_id: null },
]);
out.fileIds = fileIds(s);
s = removeAttachment(s, "a1");
out.attachmentsLeft = s.attachments.map((a) => a.id);

const payload = verdictPayload(s, [{ text: "an answer", attachment_ids: [] }]);
out.payloadRounds = payload.rounds.length;
out.payloadSpent = payload.spent;
out.payloadIdea = payload.idea;
out.payloadKeys = Object.keys(payload).sort();

console.log(JSON.stringify(out));
"""

SCRIPT = SCRIPT_TEMPLATE.replace("__SESSION_JS__", str(SESSION_JS))


@pytest.fixture(scope="module")
def result(tmp_path_factory) -> dict:
    script = tmp_path_factory.mktemp("node") / "check.mjs"
    script.write_text(SCRIPT)
    completed = subprocess.run(
        [NODE, str(script)], capture_output=True, text=True, check=True, timeout=30
    )
    return json.loads(completed.stdout)


def test_phases_follow_the_rounds(result):
    assert result["emptyPhase"] == "empty"
    assert result["cannotAnswerYet"] is False
    assert result["afterQuestions"] == "questions"
    assert result["canAnswerNow"] is True


def test_cost_accumulates_across_rounds(result):
    assert result["total"] == pytest.approx(0.60)


def test_reasks_are_counted_and_the_last_report_is_found(result):
    assert result["reasks"] == 1
    assert result["lastVerdict"] == "PROCEED"


def test_revising_the_idea_is_recorded_once(result):
    assert result["idea"] == "a revised idea"
    assert result["revisions"] == 1
    assert result["noRevisionForTheSameText"] == 1
    assert result["noRevisionForEmpty"] == 1


def test_attachments_can_be_added_and_removed(result):
    assert result["fileIds"] == ["file_1"]
    assert result["attachmentsLeft"] == ["a2"]


def test_the_verdict_payload_is_what_the_api_expects(result):
    assert result["payloadRounds"] == 3
    assert result["payloadSpent"] == pytest.approx(0.60)
    assert result["payloadIdea"] == "a revised idea"
    assert result["payloadKeys"] == ["answers", "attachments", "idea", "rounds", "spent"]
