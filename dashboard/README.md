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
Open http://localhost:4173. Vite preview serves the compiled dist assets and proxies `/state` to the unchanged Python server.
This is a local demo arrangement, not a public production hosting service. Python alone does not serve the React build.
Use two terminals and Ctrl+C to stop both processes. A real run must separately publish live_state.json.

## Controls, contracts, and security
The unchanged 500 ms polling schedule now supports a coalesced explicit refresh after HTTP 409; it never overlaps state requests.

POST /stop is implemented. Its request body is empty (an empty JSON object is also accepted), and it returns HTTP 202 `{"stop_requested": true}`. Exclusive file creation preserves an existing root STOP file. This acknowledgement does not claim cancellation, restoration, or report completion. The frontend enables STOP only for a freshly received `run_status: "running"` snapshot with a run identity; explicit confirmation is mandatory. Failed STOP requests can be manually retried because the endpoint is idempotent; no automatic retry occurs.

The UI separately displays actual `run_status`, `cleanup.done`, `report_path`, and `approval_result`. A missing report path remains unconfirmed. Approval question, reason, steps, token, and expiry are displayed.

**Approval acceptance is blocked.** `agentic/gate.py` in cab07d5 has no cross-process lock or atomic submission/closure helper. Its independent read/remove/publish operations cannot coordinate safely with a dashboard-only lock. No approved decision file is written and Approve/Deny stay disabled. POST /approve validates the supplied boolean and gate token, returning HTTP 409 `no_pending`, `stale`, or `expired` when applicable; valid submissions return HTTP 503 `gate_sync_unavailable`. Existing decisions are never overwritten. Artham must supply the shared synchronization primitive used by gate opening, consumption, terminal replies, timeout, STOP, and closure before the dashboard can perform the required temp-file + os.replace acceptance write.

The server binds to 127.0.0.1. Mutation requests must originate from a loopback client with a matching local Host and an HTTP Origin on localhost/127.0.0.1/[::1] at Vite's 5173 or 4173 ports, or the backend's own port. Foreign/missing origins, cross-site requests, oversized bodies, and non-JSON approval payloads are rejected. Restart the Python server after updating it. These checks isolate browser/LAN requests; they do not authenticate other trusted-user processes on the same computer. Operate one orchestrator against this workspace's single STOP file.

The current backend publishes cleanup.done after its restoration calls; the UI says the backend marked cleanup done, not that this dashboard independently verified container health.

The saved mock test results must not be presented as measured Docker outcomes. Empty fields render as unknown. `legacy-reference.html` preserves the vanilla reference. Manrope and IBM Plex Mono use local font fallbacks when offline.

## Optional future Python-only hosting (not implemented)
Requires separate approval to change server.py: serve dist/index.html at `/`, resolve static files inside dist with path traversal protection and correct MIME types, preserve GET /state and no-store behavior, return 404 for absent assets, and keep API handling separate from SPA fallback.
No approval or STOP handlers should be inferred from this hosting change.

## Validation
`npm run build` compiles all JSX and produces dist. Run `python tests/test_graph_mock.py` from the repository root (generates ignored mock run artifacts).
Run `node --test tests/controlApi.test.js` from dashboard for fetch-stubbed API tests. From the project root, run `python -B -m unittest discover -s dashboard/tests -p test_server.py -v` for HTTP tests using loopback and temporary files only. Atomic approval acceptance is explicitly skipped until shared gate synchronization exists. The graph mock includes actual gate-format/expiry/STOP tests with Docker replaced by fakes; it writes ignored mock run artifacts.
If Windows cannot launch npm scripts with its default shell, use `npm --script-shell=C:\Windows\System32\cmd.exe run build` (or dev/preview).
