"""Tiny synthetic cards only; never corpus labels or real experiment results."""
from copy import deepcopy
import pytest
from src.evaluate import field_equal, percentile, summarize, read_job

CARD={'title':'Synthetic Title','language':'en','recommended_level':None,'hook':None,
      'npcs':[],'locations':[],'threats':[],'rewards':[]}
COMBO={'provider':'openai','model':'synthetic','prompt':'v1','sampling':'A'}


def test_frozen_comparison_rules():
    assert field_equal('title',' A\tB  ','a b')
    assert not field_equal('title','hello!','hello')
    assert not field_equal('title','é','e')
    assert field_equal('locations',[' A ','B','B'],['b','a'])
    assert not field_equal('locations',['A','B'],['A'])
    assert field_equal('npcs',[{'name':' N ','role':None},{'name':'M','role':'Guard'}],
                            [{'name':'m','role':' guard '},{'name':'n','role':None}])
    assert not field_equal('npcs',[{'name':'N','role':None}],[{'name':'N','role':''}])
    assert not field_equal('language','en','EN')
    assert not field_equal('title',None,'')


def test_failed_missing_and_skipped_stay_in_denominators():
    inputs={v:{'text_path':'synthetic'} for v in ('ok','failed','missing','skip')}
    golden={v:{'card':deepcopy(CARD),'reference':'synthetic'} for v in inputs}
    records={'ok':{'state':'successful','attempted':True,'card':CARD,'first_pass_valid':True,'latency_s':2,'actual_calls':1,'call_costs':[.1]},
             'failed':{'state':'failed','attempted':True,'card':None,'latency_s':8,'actual_calls':2,'call_costs':[.2,.3]},
             'skip':{'state':'skipped','attempted':False}}
    s,errors=summarize(records,inputs,golden,COMBO)
    assert s['counts']==dict(attempted=2,successful=1,failed=1,missing=1,skipped=1,partial=0)
    assert s['mean_field_accuracy']==.25 and s['field_accuracy']['rewards']==.25
    assert s['populated_field_accuracy']==.25 and len(errors)==24
    assert s['first_pass_valid_pct']==s['final_valid_pct']==25
    assert s['status']=='incomplete'
    assert s['cost']['tariff_equivalent_estimate_usd']==pytest.approx(.6)
    assert s['cost']['per_1000_attempted_texts_estimate_usd']==pytest.approx(300)
    assert s['cost']['actual_provider_charge_usd'] is None
    assert s['latency']['all_attempted']['p95_s']==pytest.approx(7.7)
    assert s['latency']['failed']['p50_s']==8


def test_unknown_cost_and_partial_run_are_not_zero_or_complete():
    records={'x':{'state':'partial','attempted':True,'actual_calls':2,'call_costs':[.1,None],'latency_s':None}}
    s,_=summarize(records,{'x':{}},{'x':{'card':CARD,'reference':'synthetic'}},COMBO)
    assert s['status']=='incomplete' and s['counts']['partial']==1
    assert s['cost']['tariff_equivalent_estimate_usd'] is None
    assert s['cost']['known_tariff_subtotal_usd']==.1
    assert s['cost']['unknown_cost_attempts']==1
    assert s['latency']['all_attempted']['unknown_count']==1
    local,_=summarize(records,{'x':{}},{'x':{'card':CARD,'reference':'synthetic'}},dict(COMBO,provider='ollama'))
    assert local['cost']['actual_provider_charge_usd']==0
    assert local['cost']['hardware_cost_usd'] is None


def test_percentile_type_7():
    assert percentile([], .95) is None
    assert percentile([4], .95)==4
    assert percentile([1,2,3,4], .5)==2.5
    assert percentile([1,2,3,4], .95)==pytest.approx(3.85)


@pytest.mark.parametrize("prompt_bytes", [b"prompt", b"line one\r\nline two\r\n"])
def test_saved_attempt_costs_include_transport_and_repair(tmp_path,prompt_bytes):
    from src.pipeline import Pipeline, Operations, fingerprint
    from src.providers import ModelResponse, TokenUsage, ProviderError, Sampling
    from src.schema import card_json_schema
    from src.budget import Budget
    import json
    pricing={'model_ids':['synthetic'], 'uncached_input_per_1m':.15,'cached_input_per_1m':.075,
             'output_per_1m':.6,'reservation_input_tokens':128000}
    ops=Operations()
    prompt_path=tmp_path/'prompt.txt';prompt_path.write_bytes(prompt_bytes)
    prompt=prompt_path.read_text(encoding='utf-8')
    from src.evaluate import effective_text_hash
    schema=card_json_schema()
    identity={'provider':'openai','input_sha256':__import__('hashlib').sha256(b'synthetic').hexdigest(),
              'prompt_sha256':__import__('hashlib').sha256(prompt_bytes).hexdigest(),
              'sampling':{'temperature':.2,'top_p':.9,'max_output_tokens':2048},
              'protocol':{'schema_sha256':fingerprint(schema),'repair_prompt_sha256':__import__('hashlib').sha256(b'repair').hexdigest(),
                          'config':{'operations':ops.model_dump(mode='json')}}}
    def response(text,error=None):
        return ModelResponse('openai','synthetic','synthetic',text,'completed',TokenUsage(100,20,120,0,0),
                             'synthetic-time',.01,error=error,metadata={'sdk_call_count':1,'sdk_retries':0})
    responses=[ProviderError(response('',{'type':'APIConnectionError'})),response('bad json'),response(json.dumps(CARD))]
    class Fake:
        def generate(self,*a):
            r=responses.pop(0)
            if isinstance(r,Exception): raise r
            return r
    budget=Budget(tmp_path/'budget.sqlite3')
    try:
        result=Pipeline(Fake(),'openai',ops,pricing,budget,sleep=lambda _:None).extract('synthetic',prompt,'repair',schema,Sampling(.2,.9),identity,tmp_path/'job')
        if b'\r\n' in prompt_bytes:
            with pytest.raises(ValueError,match='Request contract mismatch'):
                read_job(tmp_path/'job',identity)
        record=read_job(tmp_path/'job',identity,expected_prompt_sha256=effective_text_hash(prompt_path))
        with pytest.raises(ValueError,match='Request contract mismatch'):
            read_job(tmp_path/'job',identity,expected_prompt_sha256='0'*64)
        assert record['actual_calls']==3 and len(record['call_costs'])==3
        assert sum(record['call_costs'])==pytest.approx(result['cost']['estimated_usd'])
        assert record['state']=='successful' and not record['first_pass_valid']
    finally:
        budget.close()


def test_incompatible_runs_rejected_before_writing_output(tmp_path,monkeypatch):
    import json
    import main
    from pathlib import Path
    from src.evaluate import evaluate
    from src.pipeline import fingerprint, file_hash, ExperimentConfig
    from src.schema import card_json_schema
    cfg_raw=json.loads(Path('config.json').read_text())
    cfg=ExperimentConfig.model_validate(cfg_raw)
    for relative in (cfg.evaluation_snapshot,cfg.dataset_descriptor,cfg.repair_prompt):
        p=tmp_path/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
    monkeypatch.setattr(main,'frozen_inputs',lambda root,cfg: ([],{'inputs':[{'text_id':'synthetic'}],'annotations':[]}))
    (tmp_path/'config.json').write_text(json.dumps(cfg_raw))
    protocol={'evaluation_snapshot_sha256':file_hash(tmp_path/cfg.evaluation_snapshot),
              'dataset_descriptor_sha256':file_hash(tmp_path/cfg.dataset_descriptor),
              'repair_prompt_sha256':file_hash(tmp_path/cfg.repair_prompt),
              'schema_sha256':fingerprint(card_json_schema()),'config':cfg.model_dump(mode='json'),'runtime':{'synthetic':'v1'}}
    dirs=[]
    for i in range(2):
        d=tmp_path/f'run{i}';d.mkdir();dirs.append(d)
        p=deepcopy(protocol);p['runtime']['synthetic']=str(i)
        (d/'run.json').write_text(json.dumps({'protocol':p,'jobs':[],'run_identity_sha256':fingerprint([])}))
    with pytest.raises(ValueError,match='incompatible'):
        evaluate(tmp_path,tmp_path/'config.json',dirs,tmp_path/'output')
    assert not (tmp_path/'output').exists()
