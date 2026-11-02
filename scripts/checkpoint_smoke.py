"""Explicitly authorized HW1 checkpoint smoke/warm-up; excluded from benchmark."""
from __future__ import annotations
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import os
from pathlib import Path
import re
import sys
import uuid
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from main import frozen_inputs
from src.pipeline import ExperimentConfig,Operations,Pipeline,file_hash,fingerprint,write_once
from src.budget import Budget,history_events,NANO
from src.providers import OpenAIProvider,Sampling
from src.ollama import OllamaProvider,OllamaConfig
from src.schema import card_json_schema


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider',choices=['openai','ollama'],required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    load_dotenv(root/'.env',override=False)
    cfg=ExperimentConfig.model_validate_json((root/'config.json').read_text())
    items,_=frozen_inputs(root,cfg)
    item=next(x for x in items if x.split=='development')
    markers=list(re.finditer(r'\[PDF_PAGE=(\d+)\]',item.content))
    for i,m in enumerate(markers):
        end=markers[i+1].start() if i+1<len(markers) else len(item.content)
        text=item.content[m.start():end]
        if len(text[m.end()-m.start():].strip())>=200:break
    else:raise ValueError('No nonempty development page')
    provider=args.provider
    model=os.getenv('PROVIDER_MODEL' if provider=='openai' else 'LOCAL_MODEL') or cfg.models[provider]
    ops=cfg.operations.model_copy(update={'transport_retries':0,'schema_repairs':0,'max_call_attempts':1})
    sampling=Sampling(**cfg.sampling['A'],max_output_tokens=ops.max_output_tokens)
    if provider=='openai' and (model not in cfg.pricing['model_ids'] or os.getenv('OPENAI_BASE_URL','https://api.openai.com/v1').rstrip('/')!='https://api.openai.com/v1'):
        raise ValueError('Provider/pricing endpoint mismatch')
    budget=Budget(root/cfg.budget['ledger_path'],cfg.budget['limit_usd'])
    for e in history_events(root/'results',cfg.pricing):budget.import_charge(e['id'],e['amount'],e['known'])
    budget.import_charge('manual_'+cfg.budget['prior_spend_reference'],int(cfg.budget['prior_spend_usd']*NANO),True)
    run_id=provider+'_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid.uuid4().hex[:8]
    out=root/'results/smoke'/run_id
    adapter=None
    try:
        runtime=None
        if provider=='openai':
            adapter=OpenAIProvider.from_env(root/'.env')
        else:
            adapter=OllamaProvider(OllamaConfig(model=model,base_url=os.getenv('OLLAMA_BASE_URL','http://localhost:11434'),
                context_size=ops.local_context_size,timeout_s=ops.local_timeout_s,sampling=sampling))
            runtime=adapter.runtime()
            if not runtime['ready']:raise ValueError('Local prerequisite: '+str(runtime['blocker']))
        identity={'kind':'checkpoint_provider_smoke' if provider=='openai' else 'checkpoint_local_warmup',
            'model':model,'provider':provider,'parent_text_id':item.text_id,'parent_input_sha256':item.text_sha256,
            'pdf_page':int(m.group(1)),'character_start':m.start(),'character_end':end,
            'prompt_sha256':file_hash(root/'prompts/v1.txt'),'schema_sha256':fingerprint(card_json_schema()),
            'source_scope':'complete development PDF page, excluded from benchmark','runtime':runtime,
            'operations':ops.model_dump(mode='json')}
        write_once(out/'source.json',{'identity':identity,'text':text})
        result=Pipeline(adapter,provider,ops,cfg.pricing,budget).extract(text,(root/'prompts/v1.txt').read_text(encoding='utf-8'),
            (root/cfg.repair_prompt).read_text(encoding='utf-8'),card_json_schema(),sampling,identity,out/'job')
        after=adapter.runtime() if provider=='ollama' else None
        write_once(out/'checkpoint_summary.json',{'kind':identity['kind'],'status':result['status'],
            'result_reference':str(out/'job/result.json'),'schema_valid':result['final_valid'],
            'generation_calls':result['actual_call_attempts'],'usage':result['usage'],
            'document_latency_s':result['document_latency_s'],'cost':result['cost'],
            'remaining_budget_usd':(budget.limit-budget.total())/NANO,'runtime_after':after,
            'failure':result['failure'],'stop_batch_reason':result['stop_batch_reason']})
        print(f"{identity['kind']}: {result['status']}; calls={result['actual_call_attempts']}; latency={result['document_latency_s']:.3f}s; failure={result['failure']}; output={out}")
        return 0 if result['final_valid'] else 2
    finally:
        if adapter:adapter.close()
        budget.close()

if __name__=='__main__':raise SystemExit(main())
