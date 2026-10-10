# ChaosPilot Control Room (React + Vite)

Requires Node 22.12+ (or Node 20.19+) and Python with the repository requirements installed.
Only React, React DOM, and Vite are used. npm is the package manager; commit the lockfile with source when approved.

## Development on Windows
From the repository root in PowerShell:
```powershell
python dashboard/server.py
```
In a second terminal:
```powershell
cd dashboard
npm ci
npm run dev
```
Open http://localhost:5173. `/state`, `/approve`, and `/stop` are proxied to Python on 127.0.0.1:8000.
The Python root URL no longer renders the frontend: its handler cannot serve JSX or asset paths.
Stop each terminal process with Ctrl+C.

## Easiest demo (one URL)
Build once, then start only the Python server and open http://127.0.0.1:8000 :
```
cd dashboard && npm ci && npm run build && cd ..
python chaospilot.py dashboard
```
The Python server serves the built app from `dashboard/dist` (plain file names under `/assets/` only).
Without a build it falls back to the old minimal page and prints a reminder.

## Hackathon demo / local production build (Vite preview, optional)
Keep the Python process above running, then from dashboard:
```powershell
npm ci
npm run build
npm run preview
```
Open http://localhost:4173. Vite preview serves the compiled dist assets and proxies `/state`, `/approve`, and `/stop` to Python.
This is a local demo arrangement, not a public production hosting service. Python alone now serves the React build too (see 'Easiest demo' above).
Use two terminals and Ctrl+C to stop both processes. A real run must separately publish live_state.json.

## Controls, contracts, and security
The unchanged 500 ms polling schedule now supports a coalesced explicit refresh after HTTP 409; it never overlaps state requests.

POST /stop is implemented. Its request body is empty (an empty JSON object is also accepted), and it returns HTTP 202 `{"stop_requested": true}`. Exclusive file creation preserves an existing root STOP file. This acknowledgement does not claim cancellation, restoration, or report completion. The frontend enables STOP only for a freshly received `run_status: "running"` snapshot with a run identity; explicit confirmation is mandatory. Failed STOP requests can be manually retried because the endpoint is idempotent; no automatic retry occurs.

The UI separately displays actual `run_status`, `cleanup.done`, `report_path`, and `approval_result`. A missing report path remains unconfirmed. Approval question, reason, steps, token, and expiry are displayed.

Approval is enabled only for a fresh, synchronized (`gate_sync.version === 1`), unexpired pending gate. The server delegates decisions to `agentic.gate.submit_decision`; the frontend sends the exact gate token and verifies the matching acknowledgement. HTTP 409 refreshes live state and blocks further submission for that gate. HTTP 503 lock contention allows manual retry only after revalidation. Network failures or unverified acknowledgements block ambiguous approval retries. No approval request is automatically retried.

The server binds to 127.0.0.1. Mutation requests must originate from a loopback client with a matching local Host and an HTTP Origin on localhost/127.0.0.1/[::1] at Vite's 5173 or 4173 ports, or the backend's own port. Foreign/missing origins, cross-site requests, oversized bodies, and non-JSON approval payloads are rejected. Restart the Python server after updating it. These checks isolate browser/LAN requests; they do not authenticate other trusted-user processes on the same computer. Operate one orchestrator against this workspace's single STOP file.

The current backend publishes cleanup.done after its restoration calls; the UI says the backend marked cleanup done, not that this dashboard independently verified container health.

The saved mock test results must not be presented as measured Docker outcomes. Missing values render as "Not available"; unknown service health is never treated as healthy. `legacy-reference.html` preserves the vanilla reference. Manrope and IBM Plex Mono use local font fallbacks when offline.

## Optional future Python-only hosting (not implemented)
Requires separate approval to change server.py: serve dist/index.html at `/`, resolve static files inside dist with path traversal protection and correct MIME types, preserve GET /state and no-store behavior, return 404 for absent assets, and keep API handling separate from SPA fallback.
No approval or STOP handlers should be inferred from this hosting change.

## Validation
`npm run build` compiles all JSX and produces dist. Run `python tests/test_graph_mock.py` from the repository root (generates ignored mock run artifacts).
Run `node --test tests/controlApi.test.js tests/controlRequest.test.js tests/navigation.test.js` from dashboard. From the project root, run `python -B -m unittest discover -s dashboard/tests -p test_server.py -v` for HTTP tests using loopback and temporary files only. The graph mock replaces Docker but writes ignored mock run/state artifacts; do not run it against a live demo workspace without accounting for those side effects.
If Windows cannot launch npm scripts with its default shell, use `npm --script-shell=C:\Windows\System32\cmd.exe run build` (or dev/preview).

## Control Room v2 foundation
The six views are local React tabs, not page loads. Arrow Left/Right, Home, and End move tab focus; Enter/Space selects. All panels remain mounted to preserve event filters and graph selections. The live-state hook and control provider remain mounted above navigation. History is deliberately empty until its contracted endpoints exist. This phase adds no fixture, archive, replay, Mystery, or Truth Oracle data source.

The sticky status strip keeps STOP and approval access available across views. New gate tokens open the global approval panel; closing it does not dismiss the gate or send a request. Approval controls use the same Phase 1 coordinator and validation. Only explicit agent-tagged events are attributed to agents, and documented responsibilities are separated from published outputs.

### Manual browser review
1. Start Python and Vite as above. Check at 1920x1080 and 1440x900, then a narrow mobile window: navigation, readable status, and no horizontal page scrolling. Maps and tables may scroll inside their own regions.
2. Navigate all six views with mouse and keyboard. Confirm the page does not reload, polling continues, and returning to Overview retains event filters/search/order; Agents retains node selections.
3. Focus or hover the information buttons. Check tap/click, Escape dismissal, pointer movement onto the tooltip, readable positioning at viewport edges, and reduced-motion settings.
4. Open Approvals from each view. With no valid synchronized gate, controls must stay disabled. Observe an existing authorized gate only; do not create a destructive run for this check.
5. Open STOP confirmation and cancel. Do not confirm STOP on a real run merely to test layout. Request acknowledgement and actual stopping/stopped/cleanup progress remain separate.
6. With no run active, stop the Python server: retained telemetry must be labelled stale, active activity unconfirmed, and mutation controls disabled. Restart it to confirm reconnection.
7. Check text contrast, visible focus, zoom/reflow, and screen-reader tab/tooltip labels. Automated markup tests do not establish full WCAG compliance or visual correctness.


### Phase 3 evidence views and fixture mode

Overview shows the published `truth` object without deriving health from missing fields.
Experiments contains a chronological, horizontally scrollable evidence timeline. Markers
require explicit timestamped injection, breach, kill-switch, or probe-recovery events.
Restore commands do not prove recovery. Events are run-wide, not attributed to a particular
experiment without an explicit backend association. Unrecognized messages remain in Activity.

Use `?fixture=gray_failure` (also `approval_pending`, `completed_with_fixes`, `idle`, or
`mystery_revealed`) for labelled static fixture data. Only the allowlisted bundled JSON
files are loaded; invalid names show an error and never fall back to live data. Fixture
mode does not mount live polling and disables all mutation controls. Remove the query
parameter and reload to return to live mode. Original fixture timestamps are preserved.

Manual review: check Overview and Experiments at 1920×1080 and 1440×900, then a narrow
viewport; keyboard-focus timeline markers to read exact event text, use Escape to dismiss,
and check horizontal overflow is contained in the timeline. In fixture mode, verify the
persistent label, disabled approval/STOP controls, and absence of `/state` or mutation
requests in browser Network. An invalid fixture must show an error, not live data.


### Phase 4 API bridge

Development and preview proxy `/mystery` and `/runs` to the existing local Python
server. `src/api/day2Api.js` supplies request-only Mystery and History adapters;
no Mystery or History UI is enabled in this phase. Mystery requires a fresh live
idle snapshot; fixture, stale, disconnected and stopped contexts fail closed.
There are no automatic retries. An acknowledgement means queued, not executed.

`GET /runs` exposes `started_at` as an ISO local calendar string parsed from the
runtime's `auto_YYYYMMDD_HHMMSS` directory name. The contract specifies no timestamp
type or timezone and the runtime records neither timezone nor an independent start
epoch. These strings preserve the recorded local time; they must not be treated as
UTC. Listing excludes invalid dates, other names, and linked directories. Report
and event reads reject links and traversal; Markdown remains untrusted plain text.
History GETs always validate loopback/Host and reject foreign Origin when supplied;
same-origin browser GETs may omit Origin. Mutation Origin requirements are unchanged.

Mystery writers serialize across dashboard processes using the directory
`runs/dashboard_mystery.lock`, publish a flushed temporary file with `os.replace`,
and never replace an already present request. Lock acquisition is bounded to five
seconds (`503 mystery_busy`); a crashed writer's abandoned lock requires operator
inspection and is never automatically removed. The backend Mystery consumer does
not participate in this lock and supplies no request/trial token. Thus dashboard
writers are coordinated, but consuming a request while the live state still says
idle remains a lifecycle race requiring a future orchestrator contract. STOP
presence and published stopping/stopped states reject new Mystery requests.
Filesystem validation assumes local operators do not maliciously replace directories
between path validation and file access; this bridge is not a hostile-filesystem service.


### Phase 5 P1 views

Experiments adds Mystery Mode, ranked plans, human impact, and prediction checks.
Diagnostics adds measured failure memory and fix summaries; Recovery shows full
contracted fix RPN comparisons and read-only diffs. Overview is unchanged.
Missing data is `Not available`; backend counters and selection order are not
recomputed. Prediction check booleans mean agreement with the prediction, not
measured recovery/data-loss booleans. Memory similarity is distinct from guess
confidence. Code suggestions remain proposed and never offer an apply action.

Mystery requires a fresh live running/idle snapshot with an identified run/trial
and a nonempty allowed menu. Confirmation is bound to those published values and
revalidated at submission; its client duplicate scope is not a backend token.
Pending approval/control actions, fixture mode, stale/disconnected data, and STOP
block submission. Opening/cancelling confirmation sends nothing. An acknowledged
request or uncertain/409 outcome blocks another request for that trial; no requests
retry automatically. A known rejection such as 400/503 requires a new explicit
confirmation and revalidation before any manual attempt. A 202 is only an accepted
request; injection and completion are shown solely through backend state. Guess
is shown only after diagnosis/reveal; answer and correctness only after reveal.
The existing consumer lifecycle race documented above remains a backend limitation.

Manual review (not covered by SSR/hook-driver tests): use keyboard navigation at
1920x1080, 1440x900, and narrow widths. Inspect `?fixture=completed_with_fixes` in
Diagnostics/Recovery and `?fixture=mystery_revealed` in Experiments; verify disabled
controls, read-only diff expansion, exact counters, and contained table scrolling.
Use a controlled live idle Mystery session to review confirmation without submitting
an experiment: open the dialog, cancel, and verify no POST. Check Escape, focus
restoration, and reduced motion in a browser. Tests mock all mutation requests and
do not verify live fault injection or native dialog focus behavior.

### Phase 6: archived evidence and presentation

History loads the existing read-only `/runs` adapter only while the History view is
active and outside fixture mode. Server order is retained, and refresh preserves
selection when the run still exists. Loading, empty, stale retained listings,
missing artifacts, malformed responses and network errors have separate messages.
Requests have a ten-second deadline; navigation and run changes abort old reads
and discard late responses. A manual refresh reloads listing and selected evidence.

The actual server parses `started_at` from the runtime directory name, **not file
metadata**. The UI labels it as directory-name-derived local calendar time without
a known timezone. It never converts those strings to UTC or uses modification times.

Recorded Event Replay shows the original `events.log` lines in original order.
Play/pause, backward/forward steps, reset, event-position slider and reading speed
operate entirely in the client. Speed is events per reading interval, not simulated
run time. Only valid leading recorded HH:MM:SS clocks are recognized; date, timezone,
elapsed duration and backend state are not reconstructed. The selected event has a
dedicated readout, and a bounded 41-line window keeps large logs from creating huge
DOM trees. The backend still transfers the full file. Changing run, refreshing or
leaving History stops playback. No replay callback imports live controls, publishes
state, invokes a mutation endpoint or sends Discord notifications.

Reports display the actual Markdown source as escaped, selectable preformatted text.
No HTML renderer or new dependency is added. Copy uses the browser Clipboard API and
reports failure; download creates a local Markdown Blob. A missing report (404) is
distinct from an empty file or a failed/malformed read. Reports are never executed.

Recovery displays only published regression scenario id, file, invariant, last status
and timestamp. `pass`, `fail` and `never_run` describe the last backend replay; neither
a missing key nor an empty list proves current recovery or absence of regression.
Partial fields say `Not available`. Epoch timestamps are explicitly displayed in UTC.
The contract does not publish a pending status or additional regression evidence.

Presentation Mode is an accessible pressed-state button in the global header, with
an explicit exit label. It enlarges typography and readouts and adapts header spacing.
All six tabs, the sticky live status strip, STOP and approval access remain available.
It does not rotate views, use fullscreen, alter permissions, or submit controls.

Validation: from dashboard, `node --test tests/*.test.js` exercises API validation,
escaped report rendering, bounded replay, real component callbacks/effects under a
hook driver, request races, fixture isolation and presentation toggle persistence,
along with all existing frontend tests. From the repository root use
`python -B -m unittest discover -s dashboard/tests -p 'test_*.py' -v`; tests redirect
artifacts to temporary directories and do not modify real runs. Build with
`npm run build`, then run `git diff --check`.

Manual review at **1920×1080** and **1440×900**:

1. Run the current Python dashboard server and Vite; restart an old Python process
   if `/runs` returns 404. Open History, refresh, change selected runs and inspect
   server timestamps and report availability. Disconnect the server to check errors
   and stale retained listing; reconnect and refresh manually.
2. Exercise replay play/pause, both steps, reset, reading speed and the slider.
   Change run and navigate away during playback; playback must stop. Inspect a
   missing/empty log through mocked tests rather than changing real run artifacts.
3. Inspect original report source, copy and download it. Verify the copied/downloaded
   text matches `report.md`. Raw HTML and Markdown links stay inert text.
4. Toggle Presentation Mode on Overview and History. Confirm six tabs, visible focus,
   STOP and approval access at both sizes; cancel any control dialog without submitting.
   Check narrow layouts, keyboard activation, tooltip Escape and reduced-motion mode.
5. Open `?fixture=gray_failure` and `?fixture=completed_with_fixes`; History must label
   archive access disabled and make no `/runs` requests. Verify Regression in Recovery
   uses only snapshot fields. Live mutation safeguards must remain disabled in fixtures.

Browser checks are separate from hook/SSR tests: those tests do not establish full
accessibility compliance, native clipboard/download behavior, or all visual states.
