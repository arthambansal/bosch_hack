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

## Hackathon demo / local production build
Keep the Python process above running, then from dashboard:
```powershell
npm ci
npm run build
npm run preview
```
Open http://localhost:4173. Vite preview serves the compiled dist assets and proxies `/state`, `/approve`, and `/stop` to Python.
This is a local demo arrangement, not a public production hosting service. Python alone does not serve the React build.
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
