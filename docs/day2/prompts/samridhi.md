# Prompt for Samridhi's assistant: Control Room v2, mystery and runs endpoints, Discord alerts

You are my coding partner for the final day of a hackathon (Bosch, "AI-driven chaos engineering for cloud-native
resilience"). Our product is ChaosPilot: a multi-agent system that maps the Docker Example Voting App
(vote -> redis -> worker -> postgres -> result), plans and injects safe faults, diagnoses root causes, applies and
verifies fixes, and reports an FMEA risk score. Judging is Sunday 16:00. Today we add our differentiators.

FIRST, read these files in the repo, in this order, before writing any code:
1. docs/day2/DAY2_CONTRACT.md   (the binding contract: shapes, signatures, file ownership, rules)
2. CONTRACT.md                   (Day 1 contract: results.json, live_state, approval gate)
3. core/contract_v5.py           (validators for every new live_state shape)
4. tests/test_contract_v5.py and tests/test_graph_mock.py
5. The files listed under "Your files" below, and any file they import.

NON-NEGOTIABLE RULES
- Edit ONLY the files listed under "Your files". If you think another file must change, stop and write me the exact
  change so I can ask its owner. Never change a function signature from DAY2_CONTRACT.md section 5.
- The repo is public: never write API keys, webhook URLs or .env files. Secrets come only from environment variables.
- Faults only ever touch the sandbox containers from config.json. Safety logic stays deterministic code.
- Every new function needs a safe fallback: on any error it logs one LIVE.event("warn", ...) line and returns the
  "not available" value from the contract. It must never crash a run.
- No invented numbers. Anything shown to users comes from a measurement, or is shown as null / "not available".
- Write a test file that runs WITHOUT Docker or network (monkeypatch core.common.docker, requests, core.llm.ask_json).
  It prints "PASS ..." lines and ends with "ALL CHECKS PASSED".
- Before you say you are done, run and show the output of:
    PYTHONPATH=. python3 tests/test_contract_v5.py
    PYTHONPATH=. python3 tests/test_graph_mock.py
    PYTHONPATH=. python3 <your new test file>
  All three must end with ALL CHECKS PASSED.
- Keep code simple and readable; comments explain WHY. Python 3.10+, standard library + requests only (no new
  dependencies unless I approve).

WHEN YOU FINISH, give me: (1) a short list of files changed, (2) how to run the feature for real, (3) what I should say
to a judge about it in two sentences, (4) anything you could not finish or verify.

## My role
I own the Control Room dashboard (React 19 + Vite in dashboard/, Python bridge dashboard/server.py) and Discord alerts.

## Your files
dashboard/** (src, server.py, tests, fixtures, README), core/notify.py, tests/test_notify.py (new)

## Context you must keep working
- The UI polls GET /state every 500 ms. Approve/Deny already works through agentic.gate.submit_decision with the exact
  gate_id; keep its 409/503 handling, the localhost/origin checks and the STOP confirmation dialog. Never auto-retry an
  approval. Existing node and Python tests must keep passing.
- dashboard/fixtures/*.json are valid sample states for every new key (idle, gray_failure, approval_pending,
  mystery_revealed, completed_with_fixes). Build against them with ?fixture=<name>; show a visible "FIXTURE DATA"
  badge whenever a fixture is loaded. Never use fixture data in live mode.
- New live_state keys: truth, mystery, memory, fixes, impact, predictions, regression (contract section 4). A missing
  key shows "Not available" — never 0 or a made-up value.

## Tasks, in priority order (commit after each, the app must always build)
P0
1. Status bar (sticky top, large type): run status, phase, active agent with a live pulse, current experiment name
   (shows "Mystery fault" with no target while hidden), kill-switch meter ticks/3, elapsed fault time vs 45 s, STOP.
2. Truth vs Monitoring hero panel (the opening moment of the demo): two large indicators, "Monitoring" (truth.monitoring)
   and "Truth" (truth.status + invariants). When status == "diverged" show a banner "GRAY FAILURE — users affected,
   monitoring is green" with the time since diverged_at, canary counts (sent / stored / pending / suspected lost),
   last lag and the failing invariants with their detail text.
3. Approval: when approval_request exists show a prominent card (not buried) with question, reason, steps, a live
   countdown to expires_at, Approve / Deny; after approval_result show who decided and how.
4. Experiment timeline: per experiment a horizontal bar with the fault window shaded, the kill-switch moment, recovery
   time and a marker when a service crashed and stayed down. Focus/hover shows the exact event text.
P1
5. "Break it yourself" panel (mystery): menu buttons from mystery.menu plus "Surprise me" -> POST /mystery. Enabled
   only when mystery.state == "idle". Step tracker injected -> detected (seconds) -> diagnosed (seconds) -> revealed.
   Before reveal show only "Something is broken. ChaosPilot is investigating..." and the live evidence; after reveal
   show guess vs answer, a big Correct / Incorrect, confidence, top 3 and the evidence list, and the running accuracy
   ("2 of 3 correct").
6. Findings and fixes: one card per fix entry: title, why, status chip (proposed / applied / verified / not improved /
   rolled back) with distinct icon + text, RPN before -> after bars, and a "View diff" drawer that renders the unified
   diff with added/removed lines coloured. Code suggestions are labelled "Suggested code change — not applied".
7. Memory badge next to the diagnosis when memory.last_hit exists: "Recognised failure — seen in <run>,
   <similarity>% match, <saved_s> s faster".
8a. Ranked plan panel (brief: "AI ranks and selects experiments with a short reason"): from plan_ranking show the
   ranked candidate list (risk score bar, fault type, target, tried tick), highlight the chosen one with the AI's
   reason, and a "fault types covered 2/3" counter.
8. Prediction scoreboard (predictions.items with tick/cross, "AI predicted N of M correctly") and impact card
   (impact.summary, votes lost / accepted, outage seconds).
P2
9. Presentation mode (button + key "P"): hides secondary panels, enlarges status bar, Truth panel, mystery panel and the
   active agent; auto-scrolls to what is happening now.
10. Run replay: GET /runs list; picking a run loads its events (GET /runs/<name>/events) and a slider scrubs through
    them, clearly labelled "REPLAY". Report button opens GET /runs/<name>/report rendered as markdown.
11. Regression tab listing regression[] with last_status.

## Server (dashboard/server.py) — contract section 7, same security checks as /stop
- POST /mystery {choice_id}: only when live_state.mystery.state == "idle"; choice_id must be "random" or an id in
  mystery.menu; 409 not_idle / already_requested, 400 unknown_choice; write runs/mystery_request.json atomically
  (tmp + os.replace) with {choice_id, by: "dashboard", submitted_at}; reply 202 {accepted: true}.
- GET /runs, GET /runs/<name>/report, GET /runs/<name>/events: only folders under runs/ starting with "auto_"; reject
  any name containing "/", "\" or ".." with 400; 404 if missing. Tests for traversal, wrong origin, each error code.

## Discord (core/notify.py) — contract section 5
notify(kind, title, text, fields=None): POST a Discord embed to os.environ["DISCORD_WEBHOOK_URL"] with requests,
timeout 3 s, colour per kind (gray_failure / kill_switch red, fix_verified green, fix_rolled_back orange, others blue),
max one message per 2 seconds (drop extras), returns True if HTTP 2xx. No URL -> return False silently. Never raises.
Never log the URL. tests/test_notify.py with requests monkeypatched.

## Design direction
Keep the current calm green/grey visual language and refine it: generous spacing, clear hierarchy, one accent colour
per meaning (red = failure/gray failure, amber = human decision, green = verified/healthy, blue = AI). It must read on
a projector at 1920x1080 and on a 1440x900 laptop with no horizontal scroll. Keyboard reachable, visible focus, WCAG AA
contrast, colour never the only signal, respect prefers-reduced-motion. Every number has a unit and comes from a key.

## Done means
npm run build passes, node tests + python tests pass, and you send screenshots of every fixture plus presentation mode.
