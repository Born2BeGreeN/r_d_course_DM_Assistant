"""Offline final HW1 report from compatible saved measurements; never calls a model."""
import argparse
import csv
import json
from pathlib import Path
import sqlite3
import sys
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.evaluate import FIELDS
from src.pipeline import canonical,file_hash,write_once,fingerprint
from src.budget import history_events,NANO


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluation',type=Path,required=True)
    parser.add_argument('--run',type=Path,action='append',required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    out=root/'results/final/hw1_20261101'
    evaluation=json.loads((args.evaluation/'summary.json').read_text(encoding='utf-8'))
    rows=evaluation['summaries']
    assert len(rows)==8
    cfg=json.loads((root/'config.json').read_text())
    guard=json.loads((root/'.tools/final_experiment_guard.json').read_text())
    for path,sha in guard['hashes'].items():
        if path=='src/evaluate.py':
            fix=json.loads((out/'evaluator_compatibility_fix.json').read_text())
            assert sha==fix['old_evaluator_sha256'] and file_hash(root/path)==fix['new_evaluator_sha256']
        else:
            assert file_hash(root/path)==sha,path
    headers=[];records=[];keys=set();protocol=None
    for run in args.run:
        assert not (run/'active.lock').exists()
        header=json.loads((run/'run.json').read_text());headers.append(header)
        assert protocol is None or protocol==header['protocol']
        protocol=header['protocol']
        for job in header['jobs']:
            i=job['identity'];key=(i['provider'],i['prompt_version'],i['sampling_name'],i['text_id'])
            assert key not in keys;keys.add(key)
            path=run/'jobs'/job['job_id']/'result.json'
            if not path.exists():continue
            r=json.loads(path.read_text());records.append((path,r))
    assert len(keys)==240
    complete=evaluation['status']=='complete'
    with sqlite3.connect((root/cfg['budget']['ledger_path']).as_uri()+'?mode=ro',uri=True) as db:
        accounted=db.execute('select sum(accounted) from charges').fetchone()[0]/NANO
        ledger_states=db.execute('select state,count(*),sum(accounted) from charges group by state').fetchall()
    events=history_events(root/'results',cfg['pricing'])
    assert abs(sum(e['amount'] for e in events)/NANO-accounted)<1e-9
    auxiliary=[]
    for path in sorted((root/'results/smoke').glob('*.json')):
        s=json.loads(path.read_text())
        auxiliary.append({'reference':str(path.relative_to(root)),'kind':s['kind'],'generation_calls':s.get('generation_calls',0),'status':s['status'],'paid':False})
    for path in sorted((root/'results/smoke').glob('*/checkpoint_summary.json')):
        s=json.loads(path.read_text());auxiliary.append({'reference':str(path.relative_to(root)),'kind':s['kind'],'generation_calls':s['generation_calls'],'status':s['status'],'paid':'provider_smoke' in s['kind']})
    failures=[{'result_reference':str(p),'text_id':r['identity']['text_id'],'combination':{k:r['identity'][k] for k in ('provider','model','prompt_version','sampling_name')},'failure':r['failure'],'latency_s':r['document_latency_s'],'call_attempts':r['actual_call_attempts']} for p,r in records if r['status']=='failed']
    errors=[json.loads(l) for l in (args.evaluation/'disagreements.jsonl').read_text(encoding='utf-8').splitlines()]
    examples=[];used=set()
    for field in ('language','recommended_level','npcs','hook','title'):
        candidates=[e for e in errors if e['field']==field and e['combination']['prompt']=='v2' and e['observed_error']=='field_mismatch']
        e=next((e for e in candidates if e['text_id'] not in used),next(iter(candidates),None))
        if e:examples.append(e);used.add(e['text_id'])
    actual_calls=sum(r['actual_call_attempts'] for _,r in records)
    retries=sum(r['transport_retry_count'] for _,r in records)
    repairs=sum(r['repair_count'] for _,r in records)
    matrix_costs=[s['cost']['tariff_equivalent_estimate_usd'] for s in rows]
    matrix_cost=None if any(c is None for c in matrix_costs) else sum(matrix_costs)
    best=max(rows,key=lambda s:(s['mean_field_accuracy'],s['final_valid_pct'],-(s['latency']['all_attempted']['p95_s'] if s['latency']['all_attempted']['p95_s'] is not None else float('inf')),-(s['cost']['tariff_equivalent_estimate_usd'] if s['cost']['tariff_equivalent_estimate_usd'] is not None else float('inf'))))
    summary={'kind':'final_hw1_experiment','status':evaluation['status'],'expected_unique_initial_executions':240,
        'terminal_records':len(records),'reused_v1_records':sum(r['identity']['prompt_version']=='v1' for _,r in records),
        'new_v2_records':sum(r['identity']['prompt_version']=='v2' for _,r in records),
        'actual_matrix_call_attempts':actual_calls,'transport_retries':retries,'repair_requests':repairs,
        'successful_records':sum(r['status']=='succeeded' for _,r in records),'failed_records':len(failures),
        'eight_rows':rows,'auxiliary_calls_excluded_from_matrix':auxiliary,
        'matrix_tariff_equivalent_estimate_usd':matrix_cost,'cumulative_accounted_usd':accounted,'remaining_budget_usd':5-accounted,
        'actual_provider_invoice_usd':None,'free_quota_charge_status':'unknown_not_assumed_free',
        'ledger_states':ledger_states,'failures':failures,'observed_disagreement_examples':examples,
        'causal_hypotheses':['Strict source-phrase and whole-set scoring can penalize partially source-correct answers; source review required.',
            'Longer instructions may interact with local context pressure or runtime; one run does not establish causation.'],
        'report_ranking':'mean field exact-match, then final validity, then p95 latency, then tariff cost',
        'provisional_candidate':best['combination'],'evaluation_reference':str(args.evaluation),'evaluation_sha256':file_hash(args.evaluation/'summary.json')}
    write_once(out/'summary.json',summary)
    hardware=json.loads((out/'hardware_verified.json').read_text(encoding='utf-8')) if (out/'hardware_verified.json').exists() else None
    write_once(out/'experiment_metadata.json',{'protocol':protocol,'protocol_sha256':fingerprint(protocol),'hardware_inventory_before_v2':hardware,
        'hardware_caveat':'Inventory is not GPU utilization/energy measurement and does not prove unchanged load across runs.',
        'frozen_artifact_hashes':guard['hashes'],'evaluation_code_sha256':file_hash(root/'src/evaluate.py'),'offline_checker_correction':json.loads((out/'evaluator_compatibility_fix.json').read_text()),
        'run_evidence':[{'path':str(p/'run.json'),'sha256':file_hash(p/'run.json')} for p in args.run],
        'prompt_hashes':{v:file_hash(root/path) for v,path in cfg['prompts'].items()},'repair_prompt_sha256':file_hash(root/cfg['repair_prompt'])})
    with (out/'matrix_records.jsonl').open('xb') as handle:
        for p,r in records:
            handle.write(canonical({'identity':r['identity'],'identity_sha256':r['identity_sha256'],'result_reference':str(p),'result_sha256':file_hash(p),
                'status':r['status'],'actual_call_attempts':r['actual_call_attempts']})+b'\n')
    def num(v,n=4):return 'unknown' if v is None else f'{v:.{n}f}'
    lines=['# Homework 1 — фінальний експеримент','',
        '**Status: '+evaluation['status']+'.** Дві моделі × v1/v2 × A/B на тих самих 30 frozen texts.','',
        f'Збережено {len(records)}/240 terminal records: {summary["successful_records"]} schema-valid, {len(failures)} failed. Повторно використано 120 сумісних v1 records (включно з failures), виконано лише відсутні v2. Часові мітки не освіжали повторними model calls.','',
        '## Валідація і protocol','',
        'Dataset 30 nonempty (10 golden / 3 development / 17 corpus), 10/10 reviewed labels і frozen hashes перевірено. Повні generation protocols v1/v2 ідентичні: code/dependencies, models, sampling, runtime version/digest/context, schema, repair, config/prices та snapshot. Різняться тільки extraction prompt identities. Prompts/labels після final comparison не змінювалися. Tests: 127 passed. Актуалізовано missing-v2 test і виправлено offline checker для CRLF/raw-versus-effective prompt hashes до фінального порівняння; scoring functions AST незмінний. Стару/нову версії checker збережено. Generation code, prompts, labels і measurements не змінювали.','',
        'OpenAI requested gpt-4o-mini, SDK retries=0; responses use strict JSON Schema. Local Ollama 0.40.13, qwen2.5:3b Q4_K_M, digest 357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b, context 8192. A temperature=0.2/top_p=0.9; B=0.8/0.9. Provider/local timeout 60/180s; один transport retry/request, один schema repair, максимум 4 attempts/execution. Однаковий finalized source text передано обом adapters.','',
        'Hardware inventory перед v2: Intel Core i7-12700H (14 cores/20 threads), RAM ~16 GiB, RTX 3050 Ti Laptop GPU та Intel Iris Xe (див. hardware_verified.json). Driver/Windows-reported memory — в metadata; utilization/energy не вимірювали. Початковий CIM probe був sandbox-denied, повторний дозволений read-only probe успішний. Inventory не доводить однаковий фоновий load під час v1/v2.','',
        '## Вісім comparison rows','',
        '| Model | Prompt / sampling | Attempted / success / failed / missing / skipped | Mean field % | Populated % | First / final valid % | p50 / p95 s | API tariff USD | USD / 1000 attempted |',
        '|---|---|---|---:|---:|---|---|---:|---:|']
    for s in rows:
        c=s['combination'];n=s['counts'];l=s['latency']['all_attempted'];cost=s['cost']
        lines.append(f"| {c['model']} | {c['prompt']} / {c['sampling']} | {n['attempted']} / {n['successful']} / {n['failed']} / {n['missing']} / {n['skipped']} | {100*s['mean_field_accuracy']:.2f} | {100*s['populated_field_accuracy']:.2f} | {s['first_pass_valid_pct']:.2f} / {s['final_valid_pct']:.2f} | {num(l['p50_s'])} / {num(l['p95_s'])} | {num(cost['tariff_equivalent_estimate_usd'],7)} | {num(cost['per_1000_attempted_texts_estimate_usd'])} |")
    lines+=['','Кожний field: denominator 10; mean: correct/80. Populated denominator виключає лише null/[]/empty string golden cells. Failed extraction — 0/8, навіть коли golden порожній. Validity denominator 30. Missing/skipped не вилучаються. Strings: whitespace/casefold only; full sets/NPC name-role pairs independent of order; enum/null exact. Це exact field match, не частковий semantic credit.','',
        '| Model / prompt / sampling | title | language | level | hook | npcs | locations | threats | rewards |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for s in rows:
        c=s['combination'];lines.append('| '+c['model']+' / '+c['prompt']+' / '+c['sampling']+' | '+' | '.join(f'{100*s["field_accuracy"][f]:.0f}%' for f in FIELDS)+' |')
    lines+=['','## Latency і failures','',
        'p50/p95: linear interpolation h=(n−1)p, Hyndman–Fan type 7. Document timers включають retries, waits, repairs і persistence. Успішні та failed durations подано окремо; unknown не підміняється нулем.','',
        '| Model / prompt / sampling | Success n / p50 / p95 s | Failed n / p50 / p95 s | Unknown durations |',
        '|---|---|---|---:|']
    for s in rows:
        c=s['combination'];ok=s['latency']['successful'];bad=s['latency']['failed'];all_=s['latency']['all_attempted']
        lines.append(f"| {c['model']} / {c['prompt']} / {c['sampling']} | {ok['n']} / {num(ok['p50_s'])} / {num(ok['p95_s'])} | {bad['n']} / {num(bad['p50_s'])} / {num(bad['p95_s'])} | {all_['unknown_count']} |")
    reason_counts={}
    for f in failures:reason_counts[f['failure']]=reason_counts.get(f['failure'],0)+1
    lines+=['', 'Observed failure reasons: `'+json.dumps(reason_counts,ensure_ascii=False)+'`. Повні refs і attempt evidence збережено; outputs не ремонтували семантично. Context/truncation є per-text failure, а не приводом вилучити текст. Silent server-side truncation без telemetry не можна повністю виключити.','',
        '## Attempts і бюджет','',
        f'Planned: 240 unique initial identities; terminal initial records: {len(records)}. Actual saved matrix call attempts **{actual_calls}**, transport retries **{retries}**, schema repair requests **{repairs}** (repair attempts входять до actual calls). Auxiliary smoke/warm-up не входять до 240 та matrix cost.','',
        '| Auxiliary record | Kind | Calls | Status |','|---|---|---:|---|']
    for a in auxiliary:lines.append(f"| `{a['reference']}` | {a['kind']} | {a['generation_calls']} | {a['status']} |")
    lines+=['',
        'Офіційні [GPT-4o Mini prices](https://developers.openai.com/api/docs/models/gpt-4o-mini), повторно звірено 01.11.2026: $0.15 input / $0.075 cached input / $0.60 output за 1M text tokens. Cached/thinking не додаються двічі. Модель у каталозі deprecated; заміни не робили.','',
        f'Matrix tariff-equivalent estimate: **${num(matrix_cost,7)}**. Сукупний homework ledger разом зі smoke/old/new calls: **${accounted:.7f}**; залишок USD 5 ліміту: **${5-accounted:.7f}**. Local API $0; hardware/energy/runtime monetary cost unknown. Actual provider invoice/free-quota charges **невідомі**, тарифна оцінка не є підтвердженням списання. Application estimates/reservations не гарантують final bill. Unknown usage зберігається unknown або conservative reservation; не приймається за нульову external charge.','',
        '## Виміряні tradeoffs v2 проти v1','']
    indexed={(s['combination']['provider'],s['combination']['prompt'],s['combination']['sampling']):s for s in rows}
    for provider in cfg['models']:
        for sampling in cfg['sampling']:
            a=indexed[(provider,'v1',sampling)];b=indexed[(provider,'v2',sampling)]
            lines.append(f"- {provider}/{sampling}: mean field delta **{100*(b['mean_field_accuracy']-a['mean_field_accuracy']):+.2f} pp**; validity delta **{b['final_valid_pct']-a['final_valid_pct']:+.2f} pp**; p50 **{num(a['latency']['all_attempted']['p50_s'])} → {num(b['latency']['all_attempted']['p50_s'])} s**; cost/1000 **{num(a['cost']['per_1000_attempted_texts_estimate_usd'])} → {num(b['cost']['per_1000_attempted_texts_estimate_usd'])}**.")
    lines+=['','Це один observation на text/config, лише 10 golden; causality/statistical superiority не доведено. V2 розроблено лише на designated development texts/results, як зафіксовано у prompts/CHANGELOG.md. Після final comparison prompt або label tuning не виконувалося.','',
        '## Disagreement examples: observed, не causal explanations','']
    for e in examples:
        c=e['combination'];lines.append(f"- `{e['text_id']}`, {c['provider']}/{c['prompt']}/{c['sampling']}, `{e['field']}`: golden `{json.dumps(e['expected'],ensure_ascii=False)}`; predicted `{json.dumps(e['predicted'],ensure_ascii=False)}`. Result: `{e['result_reference']}`; golden: `{e['golden_reference']}`. Source provenance/refs — у disagreements.jsonl.")
    lines+=['','Окремі hypotheses: вибір source phrases/title/subtitle та whole-set scoring можуть пояснювати частину mismatch, але source review потрібен для висновку. Context pressure/longer instructions можуть впливати на runtime/failures, але самі deltas не доводять причину. Невідповідність frozen golden сама по собі не доводить, що тільки модель або тільки анотація помилкова.','',
        '## Практичний вибір і межі','',
        'За прозорим пріоритетом mean field exact-match → final validity → p95 latency → tariff cost кандидат цього експерименту: **'+best['combination']['model']+' / '+best['combination']['prompt']+' / '+best['combination']['sampling']+'**. Це попередній вибір для assisted extraction із людським review, не доказ production reliability: абсолютна якість, label ambiguities і dataset size залишаються обмеженнями. Local API без зовнішнього тарифу не означає безкоштовне hardware/runtime.','',
        '## Відтворення та артефакти','',
        '```powershell',
        r'.\.tools\bin\uv.exe run python -u main.py --prompt v2 --run-id hw1_final_20261101_v2_ab',
        r'.\.tools\bin\uv.exe run python -m src.evaluate --run results/runs/hw1_baseline_20261101_v1_ab --run results/runs/hw1_final_20261101_v2_ab --output results/evaluations/hw1_final_20261101',
        r'.\.venv\Scripts\python.exe -X utf8 scripts/report_final.py --evaluation results/evaluations/hw1_final_20261101 --run results/runs/hw1_baseline_20261101_v1_ab --run results/runs/hw1_final_20261101_v2_ab',
        '```','',
        'Команди generation/evaluation вже виконані; для повторного аналізу використовуйте новий output path. Не запускайте matching measurements повторно: main --resume має вимагати повного identity match; failures також є terminal records.','',
        'Final summary та metadata: `results/final/hw1_20261101/`. Eight-row metrics, field_metrics.csv (64 field rows) і disagreements.jsonl: `results/evaluations/hw1_final_20261101/`. Matrix records JSONL містить 240 source result refs/hashes, а не копії для повторного billing. Raw historical results, warm-ups і smoke reports збережено.']
    path=root/'REPORT.md'
    if path.exists():raise ValueError('REPORT.md exists; preserve it and choose an explicit revision')
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(f'Final report: {evaluation["status"]}; {len(records)} terminal records; {actual_calls} matrix attempts; accounted USD {accounted:.7f}')

if __name__=='__main__':main()
