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

## Contracts and safety
Polling waits 500 ms after each response, times out after 4 seconds, retains the last snapshot on errors, and aborts/tidies timers on unmount.
No mutation routes are called in the shipped configuration. Approval and STOP remain disabled; the Python server has no POST handlers yet.

`src/api/controlApi.js` prepares reusable `approve`, `deny`, and `requestStop` functions. Both production adapters in `CONTROL_CONTRACTS` are deliberately null. An attempted call fails before fetch. No gate token, HTTP payload, or acknowledgement schema is inferred from the boolean approval-file contract.

Before enabling either adapter, finalize and verify the real endpoint, request body/headers, authoritative gate/run identity, expiry and duplicate handling, and acceptance response. A verified adapter must implement `getContext(snapshot)`, `buildRequest(context, decision)`, and `verifyAcknowledgement(response)`. The adapter's frontend `context.key` scopes feedback and duplicate guards; it is not a new field in `/state` or an invented backend token.

The shared control provider keeps both STOP buttons in sync, suppresses duplicate submissions, blocks automatic retries, and renders loading/error/acknowledgement feedback. Uncertain outcomes remain blocked for that scope. Acknowledgement never means experiment execution or cleanup has completed.

Use **Review STOP confirmation** in the safety section to inspect the native confirmation dialog without sending a request. Its submission remains disabled. Future STOP submission must pass through confirmation and recheck the current run context. Dialog Escape/Cancel sends nothing.
The saved mock test results must not be presented as measured Docker outcomes. Empty fields render as unknown.
`legacy-reference.html` preserves the working vanilla frontend; Vite can serve this reference path, but it is not the new entry point.
Manrope and IBM Plex Mono fonts load from Google Fonts; local Segoe UI/Arial and Consolas fallbacks work offline.

## Optional future Python-only hosting (not implemented)
Requires separate approval to change server.py: serve dist/index.html at `/`, resolve static files inside dist with path traversal protection and correct MIME types, preserve GET /state and no-store behavior, return 404 for absent assets, and keep API handling separate from SPA fallback.
No approval or STOP handlers should be inferred from this hosting change.

## Validation
`npm run build` compiles all JSX and produces dist. Run `python tests/test_graph_mock.py` from the repository root (generates ignored mock run artifacts).
Run `node --test tests/controlApi.test.js` from dashboard for isolated control API tests; these use fetch stubs and do not contact the backend or write approval/STOP files.
If Windows cannot launch npm scripts with its default shell, use `npm --script-shell=C:\Windows\System32\cmd.exe run build` (or dev/preview).
