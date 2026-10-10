# Tejas validation and integration handoff

## Completed on 10 Oct 2026

- Fresh checkout on branch `tejas`; old local folder untouched.
- Requirements installed in a local `.venv`: requests and pinned LangGraph 1.2.14 plus transitive dependencies. Source cloned separately under the existing ignored `sandbox/app-src`.
- Repository and both supplied attachments inspected. Base already contains Cartographer `recon_agent` and Diagnostician migration; `core/agents.py` absent. No deletion or shared migration was attempted.
- `python tests/test_graph_mock.py`: seven checks passed; **ALL CHECKS PASSED**. These are simulations, including their synthetic loss and fix numbers, not real findings.
- `python docs/test_tejas.py`: **TEJAS CHECKS PASSED**. Covers path traversal/absolute escapes, bounded read, literal grep, source W1 evidence, open status, zero detection delay, missing Observer timings, fact-selection fallback, untested heatmap cells and HTML escaping.
- Changed Python files compile; `git diff --check` passes.
- Docker compose validated and fresh `chaos-*` sandbox created; unrelated existing containers left alone.
- Real map + 15-second baseline + explicitly approved single Redis-kill validation. Raw copies in `docs/evidence/e1`; details in FINDINGS.md.

## Contract preservation

Only Tejas-owned files are changed: Cartographer, Reporter, `core/code_tools.py`, `core/report_extras.py`, README and docs. No schemas, state keys, Knowledge Store tables, planner, Governor, engine, sandbox compose, TESTLOG or Dipen files change. Existing `threat_model.hypotheses_to_test` remains strings. Section 8.2 typed Hypothesis messages are saved as a separate JSON artifact pending Artham's contract integration. Reporter adds only its existing documented `summary` field; supplemental timings/heatmap live in reports.

## Cartographer citation-validation update

AI hypotheses no longer have to equal the predefined W1 record. Each accepted hypothesis must retain the exact Section 8.2 keys, have a unique ID, use `source: code` and `status: open`, and name only services in the dependency map. Evidence strings use `relative/path:positive_line_number: exact complete source line`. Each quote is checked against the current source with the existing confined, read-only `read_file` tool; only outer indentation is ignored. Function declaration lines can be cited alongside mechanism lines. At most 20 hypotheses and 12 citations per hypothesis are accepted per response.

Malformed records, duplicate IDs, nonexistent or stale lines, fabricated/partial quotes, traversal paths, absolute paths and unknown services are rejected. Valid findings in a mixed response survive independently. If no source hypothesis survives, the existing W1/dependency fallback is used with `source: rules`. Verified hypotheses are projected into the existing string list and separate typed artifact; additional model keys never enter the shared threat model. Cached model answers are not mutated.

The new regression scenarios in `docs/test_tejas.py` use a small synthetic pop-before-save source fixture and simulated model replies. They demonstrate acceptance and rejection behaviour, not live AI discovery or a measured application failure. Citation verification proves that quoted text exists; it does not prove the proposed causal mechanism. All findings stay open pending experiment evidence. This update touches only the Cartographer, Tejas's test script and this document.

Validation of this update: the existing graph mock returned **ALL CHECKS PASSED** (7 checks); the isolated hypothesis-logic tests returned **HYPOTHESIS LOGIC CHECKS PASSED** with source-tool responses mocked; Python compilation and `git diff --check` passed. The full `docs/test_tejas.py` suite was attempted but blocked at the existing filesystem confinement test by `PermissionError: [WinError 5]` while resolving its temporary source root. Both available Python runtimes hit the same sandbox restriction, and the session approval policy disallowed elevated execution. Re-run `python docs/test_tejas.py` in the user's normal local terminal before committing/pushing this update. This is not recorded as a full-suite pass or a live-model evaluation.

## Required owner follow-ups

**Artham:** fix Windows stdin `select()` approval, require human approval for data-store kills, fix the `max=1` combined fallback, and integrate typed Hypothesis persistence through the canonical schemas/state when ready. Tejas does not change those contracts.

**Pratham:** supply Observer summaries with `mttd_s` and `mttr_s` in the result's observation artifact when integrated by Artham. Until then end-to-end timing remains unknown; legacy probe timing stays separate. Unique canary evidence and regression/trade-off measurements remain required.

**Dipen:** no changes to his files or shared deletion are needed at this base. Typed Hypothesis records can be persisted by his Knowledge Store once the agreed integration exists. No database-schema assumptions or migrations were introduced here.

**Team:** validate live LLM behaviour with a key, pin Docker image/source provenance, test on a second laptop, and complete the official team form. No external coordination message has been sent from this session; this document supplies the reviewable handoff.

The video is a 180-second captioned evidence walkthrough, with no audio and no simulated full-demo claims. It is not evidence that mystery mode, fixes or full blueprint integration ran.

## Day 2 implementation checks — 10 Oct 2026

Commands executed with the existing .venv interpreter and PYTHONPATH=.

| Check | Exit | Final output |
|---|---|---|
| tests/test_contract_v5.py | 0 | ALL CHECKS PASSED (35 PASS lines) |
| tests/test_graph_mock.py | 0 | ALL CHECKS PASSED (22 PASS lines) |
| tests/test_regression.py | 0 | ALL CHECKS PASSED (4 grouped checks) |
| tests/test_report_v2.py | 0 | ALL CHECKS PASSED (3 grouped checks) |
| docs/test_tejas.py (additional existing suite) | 1 | Windows WinError 5 in existing SOURCE_ROOT.resolve(strict=True) |

Complete outputs are in docs/evidence/day2_*_test.txt. The extra source suite is
blocked by this session's Windows filesystem access, so it must be rerun in the
user's normal activated terminal before publishing. Source confinement was not
weakened. The interpreter also prints a Miniconda location warning, despite running
the four Day 2 suites successfully.

Changed Python files compile, workflow YAML parses and git diff --check passes.
Ownership audit confirms only Tejas-owned repository files changed.

Live/remote blockers: Docker named-pipe permission denied; GitHub remote query
failed with getaddrinfo() thread failed to start. No commit or push was made, no
Actions run was observed, and no live replay occurred. The assignment's two teammate
runs and final recording/form details remain unavailable. See TEJAS_HANDOFF.md.
