// Presentation of agentic/graph.py. Overview edges are a subset; node inspection
// and the route table expose every transition, including all feedback loops.
export const WORKFLOW_NODES = [
  { id: 'cartographer', label: 'Cartographer', code: 'CA', type: 'reasoning', x: 24, y: 88, description: 'Builds the application model and proposes testable failure hypotheses.' },
  { id: 'experimenter', label: 'Experimenter', code: 'EX', type: 'reasoning', x: 202, y: 88, description: 'Chooses the next experiment using hypotheses, prior outcomes, and safety feedback.' },
  { id: 'governor', label: 'Safety Governor', code: 'SG', type: 'support', x: 380, y: 88, description: 'Checks the proposed experiment against deterministic safety policy.' },
  { id: 'approval', label: 'Approval gate', code: 'HG', type: 'support', x: 558, y: 88, description: 'Pauses for human sign-off when required; otherwise passes the approved proposal on.' },
  { id: 'execute', label: 'Executor', code: 'XE', type: 'support', x: 736, y: 88, description: 'Runs fault injection, monitoring, restoration, and the delivery audit.' },
  { id: 'evaluate', label: 'Evaluator', code: 'EV', type: 'support', x: 914, y: 88, description: 'Computes FMEA results and decides whether an investigation is needed.' },
  { id: 'remediator', label: 'Remediator', code: 'RE', type: 'reasoning', x: 202, y: 278, description: 'Chooses applicable fixes and sends pending changes to verification.' },
  { id: 'verify', label: 'Verifier', code: 'VF', type: 'support', x: 440, y: 278, description: 'Re-runs targeted experiments and compares their measured risk scores.' },
  { id: 'reporter', label: 'Reporter', code: 'RP', type: 'support', x: 678, y: 278, description: 'Produces the findings report and deterministic resilience score.' },
  { id: 'diagnostician', label: 'Diagnostician', code: 'DI', type: 'reasoning', x: 914, y: 278, description: 'Investigates anomalous results and returns evidence to the Experimenter.' },
];

export const WORKFLOW_ROUTES = [
  { from: 'START', to: 'cartographer', when: 'Run begins', path: 'M95 55V88', overview: true },
  { from: 'cartographer', to: 'experimenter', when: 'Application model returned', path: 'M166 128H202', overview: true },
  { from: 'experimenter', to: 'governor', when: 'An experiment is proposed', path: 'M344 128H380', overview: true },
  { from: 'experimenter', to: 'remediator', when: 'No proposal remains', path: 'M273 168V278', overview: true },
  { from: 'governor', to: 'approval', when: 'Policy approves the proposal', path: 'M522 128H558', overview: true },
  { from: 'governor', to: 'experimenter', when: 'Rejected; fewer than 3 consecutive rejections', path: 'M451 88V60H273V88' },
  { from: 'governor', to: 'remediator', when: 'Rejected; 3 consecutive rejections reached', path: 'M451 168V220H273V278' },
  { from: 'approval', to: 'execute', when: 'Review remains approved', path: 'M700 128H736', overview: true },
  { from: 'approval', to: 'experimenter', when: 'Human denies the proposal', path: 'M629 88V35H273V88' },
  { from: 'execute', to: 'evaluate', when: 'Experiment result returned', path: 'M878 128H914', overview: true },
  { from: 'evaluate', to: 'diagnostician', when: 'Result is anomalous', path: 'M985 168V278', overview: true },
  { from: 'evaluate', to: 'experimenter', when: 'Result needs no investigation', path: 'M985 88V20H273V88' },
  { from: 'diagnostician', to: 'experimenter', when: 'Investigation returned', path: 'M985 358V391H178V212H273V168' },
  { from: 'remediator', to: 'verify', when: 'A fix is pending verification', path: 'M344 318H440', overview: true },
  { from: 'remediator', to: 'reporter', when: 'No fix is pending', path: 'M273 358V375H749V358' },
  { from: 'verify', to: 'reporter', when: 'Results improved, or 2 fix attempts reached', path: 'M582 318H678', overview: true },
  { from: 'verify', to: 'remediator', when: 'Not improved; fewer than 2 fix attempts', path: 'M511 278V239H273V278' },
  { from: 'reporter', to: 'END', when: 'Report returned', path: 'M749 358V396', overview: true },
];

export const nodeLabel = id => WORKFLOW_NODES.find(node => node.id === id)?.label || id;
export const activeNodeId = value => ({ executor: 'execute', evaluator: 'evaluate', verifier: 'verify', human: 'approval' }[value] || value);
