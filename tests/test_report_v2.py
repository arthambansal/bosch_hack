"""Offline Report v2 checks. Run: python tests/test_report_v2.py."""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import report_extras as E
from core.contract_v5 import validate_impact
from agentic.nodes import reporter as R


def main():
    r = {'id':'E2', 'name':'Redis kill', 'status':'aborted', 'abort_reason':'KILL SWITCH: error threshold',
         'delivery':{'sent':40,'lost':17}, 'fault_window_s':4.5, 'recovery_s':1.5,
         'steps':[{'type':'kill','target':'redis'}], 'stuck_services':['worker'],
         'guard_log':[{'t':3.5,'reasons':['error threshold']}],
         'probes':{'vote':{'n':10,'ok':6},'result':{'n':30,'ok':30}}}
    with patch.object(E.LIVE,'event'), patch.object(E.LIVE,'set'), \
         patch('core.common.docker',side_effect=AssertionError('Docker forbidden')), \
         patch('requests.sessions.Session.request',side_effect=AssertionError('network forbidden')), \
         patch('core.llm.ask_json',return_value=(None,'mock')), patch.object(E,'ask_json',return_value=(None,'mock')):
        impact=E.impact_of(r)
        assert validate_impact(impact)==[]
        assert impact['votes_lost']==17 and impact['votes_accepted']==40
        assert impact['failed_requests_pct']==10 and impact['outage_s']==4.5
        assert 'proxy' in impact['summary']
        assert E.impact_of({})['outage_s'] is None
        assert E.impact_of(dict(r,probes={'vote':{'n':10,'ok':10}}))['outage_s']==0
        assert E.impact_of(dict(r,probes={'vote':{'n':10,'ok':6,'outage_s':2.1}}))['outage_s']==2.1
        assert E.impact_of(dict(r,probes={'vote':{'n':10,'ok':6},'result':{}}))['failed_requests_pct'] is None
        assert validate_impact(E.impact_of(None))==[]
        print('PASS impact weighted by requests, measured/proxy outage labelled, unknown values preserved')
        results=[dict(r,prediction_check={'probes':True,'data_loss':False},memory_hit=True),
                 {'prediction_check':{'recovers':True,'data_loss':None},'memory_hit':False}, {}]
        trials=[{'correct':{'top1':True,'top3':True,'target':True},'guess':{'memory_hit':False}},
                {'correct':{'top1':False,'top3':True,'target':False},'guess':{'memory_hit':True}}]
        ver={'fix_status':{'a':'verified','b':'rolled_back','c':'not_improved'}}
        card=E.scorecard(results,ver,trials)
        assert card=={'predictions':{'right':1,'total':2},'mystery':{'trials':2,'top1':1,'top3':2,'target':1},
                      'fixes':{'verified':1,'rolled_back':1,'not_improved':1},'memory_hits':2}
        assert E.scorecard([],{},None)['mystery']['trials'] is None
        assert E.scorecard([],{},[])['mystery']['trials']==0
        assert E.scorecard([],{},[{}])['mystery']['top1'] is None
        assert E.scorecard([{'prediction_check':True}],{},[])['predictions']['right'] is None
        assert 'Not available' in E.postmortem(None,None,None)
        inv={'root_cause':'worker exited','evidence':['<script>bad()</script>','worker code 1'],'suggested_fix':'restart policy'}
        pm=E.postmortem(r,inv,impact)
        assert all(x in pm for x in ('Summary','Impact','Timeline','Root cause','What went well','Action items','+3.5 s','worker code 1'))
        print('PASS scorecard counts match hand calculation; postmortem cites timeline and evidence')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runs') as d, patch.object(E,'RUNS_DIR',d), \
             patch.object(R,'run_dir',return_value=d), patch.object(R,'export_scenario'), \
             patch('core.regression.list_scenarios',return_value=[]), patch.object(R,'list_scenarios',return_value=[]):
            state={'offline':True,'results':[r], 'investigations':{'E2':inv},'fmea':[],
                   'verification':ver,'rolled_back':['b'],'fixes':[], 'graph':{'services':{'redis':{}}}}
            report=R.reporter_node(state)
            md=Path(report['report']['path_md']).read_text(encoding='utf-8')
            html=Path(d,'report.html').read_text(encoding='utf-8')
            for heading in ('AI scorecard','Impact','Postmortems','Never-again scenarios','Before / after'):
                assert heading in md and heading in html
            assert 'rolled_back' in md and '<script>bad()</script>' not in html
            rollback_state = dict(state, fixes=[{'id':'b','for':['E2'],'kind':'compose',
                                  'why':'regressed','status':'rolled_back','rpn':[{'id':'E2','before':30,'after':270}]}])
            sections = '\n'.join(E.day2_sections(rollback_state))
            assert '| b | E2 | 30 | 270 | rolled_back |' in sections
            Path(d,'mystery_trials.jsonl').write_text('bad json')
            assert 'Not available' in '\n'.join(E.day2_sections(state))
            with patch.object(E,'ask_json',side_effect=RuntimeError('LLM down')):
                assert R.reporter_node(state)['report']['summary']
        print('PASS Reporter integration produces both formats, escapes HTML, retains rollback and AI fallback')
    print('ALL CHECKS PASSED')


if __name__=='__main__':
    main()
