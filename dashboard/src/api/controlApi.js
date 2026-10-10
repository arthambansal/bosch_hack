import { obj, num } from '../data.js';

export const APPROVAL_BLOCKER = 'Approval submission is unavailable: the orchestrator has no shared gate claim/closure synchronization.';

export function pendingGateContext(snapshot, now = Date.now() / 1000) {
  const gate = obj(snapshot.approval_request);
  if (snapshot.run_status !== 'running' || snapshot.agent_active !== 'human'
    || typeof gate.gate_id !== 'string' || !gate.gate_id
    || !num(gate.created_at) || !num(gate.expires_at) || gate.created_at > now
    || gate.expires_at <= now || gate.expires_at <= gate.created_at
    || obj(snapshot.approval_result).gate_id === gate.gate_id) return null;
  return { key: gate.gate_id, gate_id: gate.gate_id, expires_at: gate.expires_at, request: gate };
}

// STOP is implemented and tested in dashboard/server.py. Approval remains
// deliberately unconfigured: gate.py provides no cross-process synchronization.
export const CONTROL_CONTRACTS = Object.freeze({
  approval: null,
  stop: Object.freeze({
    verified: true,
    getContext(snapshot) {
      return snapshot.run_status === 'running' && typeof snapshot.run_dir === 'string' && snapshot.run_dir
        ? { key: snapshot.run_dir, run_dir: snapshot.run_dir } : null;
    },
    buildRequest(context) {
      if (typeof context.run_dir !== 'string' || context.key !== context.run_dir) {
        throw new ControlRequestError('No verified active run is available for STOP.');
      }
      return {}; // POST /stop has no request body.
    },
    async verifyAcknowledgement(response) {
      return response.status === 202 && response.headers.get('content-type')?.includes('application/json')
        && (await response.json()).stop_requested === true;
    },
  }),
});

export class ControlRequestError extends Error {
  constructor(message, { status = null, uncertain = false, code = null } = {}) {
    super(message);
    this.name = 'ControlRequestError';
    this.status = status;
    this.uncertain = uncertain;
    this.code = code;
  }
}

function configured(adapter) {
  return adapter?.verified === true
    && typeof adapter.getContext === 'function'
    && typeof adapter.buildRequest === 'function'
    && typeof adapter.verifyAcknowledgement === 'function';
}

function usableContext(context) {
  // `key` is an adapter-owned frontend identity used for request scoping. Its
  // extraction from an authoritative run/gate is deliberately unimplemented.
  return context && typeof context.key === 'string' && context.key.length > 0;
}

export function createControlApi(contracts = CONTROL_CONTRACTS) {
  function contextFor(kind, snapshot) {
    const adapter = contracts[kind];
    if (!configured(adapter)) return null;
    try {
      const context = adapter.getContext(snapshot);
      return usableContext(context) ? context : null;
    } catch {
      return null; // Missing or malformed gate/run evidence must fail closed.
    }
  }

  async function send(kind, context, { signal, decision, confirmed = false } = {}) {
    const adapter = contracts[kind];
    if (!configured(adapter) || !usableContext(context)) {
      throw new ControlRequestError('This action is unavailable until its backend contract and safety integration are verified.');
    }
    if (kind === 'stop' && confirmed !== true) {
      throw new ControlRequestError('Emergency STOP requires explicit confirmation.');
    }
    // Only a verified adapter may serialize the payload or interpret a reply.
    // The approved boolean file format does not establish an HTTP body format.
    const request = adapter.buildRequest(context, decision);
    if (!request || typeof request !== 'object') {
      throw new ControlRequestError('The verified integration did not produce a request.');
    }
    const endpoint = kind === 'approval' ? '/approve' : '/stop';
    let response;
    try {
      response = await fetch(endpoint, {
        method: 'POST', body: request.body, headers: request.headers,
        credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal,
      });
    } catch {
      throw new ControlRequestError('No acknowledgement was received. The request may have reached the backend; inspect live state before retrying.', { uncertain: true });
    }
    if (!response.ok) {
      let code = null;
      try { code = (await response.json()).error; } catch { /* never display a raw HTML error */ }
      const uncertain = code !== 'gate_sync_unavailable'
        && (response.status === 408 || (response.status >= 500 && response.status !== 501));
      const gateErrors = { no_pending: 'No approval gate is pending.', stale: 'This approval gate is stale.', expired: 'This approval gate has expired.', gate_sync_unavailable: APPROVAL_BLOCKER };
      const message = gateErrors[code] || (uncertain ? `The backend returned HTTP ${response.status}; receipt is unconfirmed. Inspect live state before retrying.`
        : response.status === 501 ? 'The backend does not implement this action.'
        : response.status === 409 ? 'The backend rejected a stale, closed, or conflicting request.'
          : `The backend rejected the request (HTTP ${response.status}).`);
      throw new ControlRequestError(message, {
        status: response.status,
        uncertain,
        code,
      });
    }
    let acknowledged = false;
    try {
      acknowledged = await adapter.verifyAcknowledgement(response);
    } catch {
      // A 2xx reply or unreadable body does not establish acceptance.
    }
    if (acknowledged !== true) {
      throw new ControlRequestError('The response did not verify acceptance. Inspect live state before retrying.', { uncertain: true });
    }
    return { acknowledged: true }; // Client result only; never a cleanup result.
  }

  return {
    getApprovalContext: snapshot => contextFor('approval', snapshot),
    getStopContext: snapshot => contextFor('stop', snapshot),
    approve: (context, options) => send('approval', context, { ...options, decision: true }),
    deny: (context, options) => send('approval', context, { ...options, decision: false }),
    requestStop: (context, options) => send('stop', context, options),
  };
}

export const controlApi = createControlApi();
