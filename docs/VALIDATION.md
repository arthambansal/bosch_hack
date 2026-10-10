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

## Required owner follow-ups

**Artham:** fix Windows stdin `select()` approval, require human approval for data-store kills, fix the `max=1` combined fallback, and integrate typed Hypothesis persistence through the canonical schemas/state when ready. Tejas does not change those contracts.

**Pratham:** supply Observer summaries with `mttd_s` and `mttr_s` in the result's observation artifact when integrated by Artham. Until then end-to-end timing remains unknown; legacy probe timing stays separate. Unique canary evidence and regression/trade-off measurements remain required.

**Dipen:** no changes to his files or shared deletion are needed at this base. Typed Hypothesis records can be persisted by his Knowledge Store once the agreed integration exists. No database-schema assumptions or migrations were introduced here.

**Team:** validate live LLM behaviour with a key, pin Docker image/source provenance, test on a second laptop, and complete the official team form. No external coordination message has been sent from this session; this document supplies the reviewable handoff.

The video is a 180-second captioned evidence walkthrough, with no audio and no simulated full-demo claims. It is not evidence that mystery mode, fixes or full blueprint integration ran.
