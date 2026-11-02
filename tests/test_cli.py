"""Read-only CLI checks: adapters must never be constructed in dry-run."""
from argparse import Namespace
import json
import main


def arguments():
    return Namespace(config='config.json',dry_run=True,provider='all',prompt='all',sampling='all',text=None,run_id=None,resume=None)


def test_default_dry_run_keeps_complete_matrix(capsys,monkeypatch):
    def no_adapter(*args,**kwargs):
        raise AssertionError('Dry-run must not construct adapters')
    monkeypatch.setattr(main,'OpenAIProvider',no_adapter)
    monkeypatch.setattr(main,'OllamaProvider',no_adapter)
    args=arguments()
    assert main.run(args)==0
    plan=json.loads(capsys.readouterr().out)
    assert plan['planned_initial_executions']==240 and plan['model_generation_calls']==0
    assert plan['errors']==[]
    args.prompt='v1'
    assert main.run(args)==0
    assert json.loads(capsys.readouterr().out)['planned_initial_executions']==120


def test_missing_v2_preserves_requested_matrix(capsys,monkeypatch,tmp_path):
    original=main.within
    def simulated_missing(root,path):
        return tmp_path/'missing_v2.txt' if path=='prompts/v2.txt' else original(root,path)
    monkeypatch.setattr(main,'within',simulated_missing)
    assert main.run(arguments())==2
    plan=json.loads(capsys.readouterr().out)
    assert plan['planned_initial_executions']==240 and plan['model_generation_calls']==0
    assert any('Missing required prompt v2' in e for e in plan['errors'])
