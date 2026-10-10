"""No Docker/network regression checks. Run: python tests/test_regression.py."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import regression as R
from core.common import load_config
from core.contract_v5 import validate_regression


def main():
    cfg = load_config()
    good = {'status': 'completed', 'recovery_s': 1, 'delivery': {'lost': 0}, 'stuck_services': []}
    bad = dict(good, id='E2', name='Redis crash', steps=[{'type': 'kill', 'target': 'redis', 'delay_s': 0}],
               delivery={'lost': 17}, stuck_services=['worker'], recovery_s=2, fault_window_s=20)
    evidence = {'evidence': ['worker exited code 1', '17 votes absent after settling']}
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runs') as d, patch.object(R, 'SCENARIOS', Path(d)), \
         patch.object(R, 'RUNS_DIR', d), patch.object(R, 'STOP_FILE', str(Path(d)/'STOP')), patch.object(R.LIVE, 'event'), \
         patch('core.common.docker', side_effect=AssertionError('Docker forbidden')), \
         patch('requests.sessions.Session.request', side_effect=AssertionError('network forbidden')), \
         patch('core.llm.ask_json', side_effect=AssertionError('AI forbidden')):
        assert R.export_scenario(good, evidence, 'fixture') is None
        assert R.export_scenario(dict(bad, status='refused'), evidence, 'fixture') is None
        assert R.export_scenario(dict(bad, abort_reason='injection failed'), evidence, 'fixture') is None
        assert R.export_scenario(bad, {}, 'fixture') is None
        assert R.export_scenario(dict(bad, fault_window_s=None), evidence, 'fixture') is None
        path = R.export_scenario(bad, evidence, 'fixture')
        body = json.loads(Path(path).read_text())
        assert body['invariants'] == ['no_vote_loss', 'no_stuck_services', 'recovers_within_s:2']
        original = Path(path).read_bytes()
        assert R.export_scenario(bad, evidence, 'changed') is None
        assert Path(path).read_bytes() == original
        assert validate_regression(R.list_scenarios()) == []
        assert all(r['last_status'] == 'never_run' for r in R.list_scenarios())
        print('PASS export only confirmed failures, requires quotes, preserves originals, valid list shape')
        engine = Mock()
        engine.run_experiment.return_value = good
        with patch('core.engine.Engine', return_value=engine) as factory, patch('agentic.gate.ask_human', return_value='yes') as gate:
            outcome = R.replay(path, cfg)
            assert outcome['passed'] is True, outcome
            assert engine.run_experiment.call_count == 1
            artifacts = list(Path(d).glob('replay_*/results.json'))
            assert len(artifacts) == 1 and json.loads(artifacts[0].read_text())[0] == good
            assert gate.call_count == 1
            assert engine._restore_all.called and engine.prober.stop.called
            assert all(r['last_status'] == 'pass' for r in R.list_scenarios())
            for change in ({'delivery': {'lost': 1}}, {'delivery': {}}, {'stuck_services': ['worker']},
                           {'stuck_services': None}, {'recovery_s': None}, {'recovery_s': 3}, {'status': 'refused'},
                           {'status': 'aborted', 'abort_reason': 'injection failed'}):
                engine.run_experiment.return_value = dict(good, **change)
                assert R.replay(path, cfg)['passed'] is False, change
            engine.run_experiment.side_effect = RuntimeError('engine failure')
            engine._restore_all.reset_mock(); engine.prober.stop.reset_mock()
            assert R.replay(path, cfg)['passed'] is False
            assert engine._restore_all.called and engine.prober.stop.called
            engine.run_experiment.side_effect = None
            engine.run_experiment.return_value = good
            engine._restore_all.side_effect = OSError('restore failed')
            engine.prober.stop.reset_mock()
            assert R.replay(path, cfg)['passed'] is False
            assert engine.prober.stop.called
            engine._restore_all.side_effect = None
            print('PASS replay checks measured invariants and always restores/stops, including exceptions')
            count = factory.call_count
            gate.return_value = 'no'
            assert R.replay(path, cfg)['passed'] is False
            assert factory.call_count == count
            gate.return_value = 'yes'
            invalid_steps = [[{'type':'kill', 'target':'outside'}],
                             [{'type':'kill', 'target':'redis'}, {'type':'kill', 'target':'db'}],
                             [{'type':'pause','target':'vote','delay_s':float('inf')}],
                             [{'type':'kill','target':'worker'}]*3]
            for steps in invalid_steps:
                Path(path).write_text(json.dumps(dict(body, steps=steps)))
                assert R.replay(path,cfg)['passed'] is False
                assert factory.call_count == count
            Path(path).write_text(json.dumps(dict(body, invariants=['unknown'])))
            assert not R.replay(path,cfg)['passed']
            assert factory.call_count == count
            Path(path).write_text(json.dumps(body))
            Path(R.STOP_FILE).touch()
            assert not R.replay(path,cfg)['passed']
            assert factory.call_count == count
            print('PASS sandbox/Governor limits, unknown invariants, STOP and denied approval block injection')
        assert not R.replay(str(Path(d)/'missing.json'),cfg)['passed']
        (Path(d)/'.status.json').write_text('bad json')
        assert R.list_scenarios() == []
        assert R.export_scenario(None,None,None) is None
        print('PASS missing/malformed inputs return safe defaults')
    print('ALL CHECKS PASSED')


if __name__ == '__main__':
    main()
