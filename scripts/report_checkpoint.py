"""Offline checkpoint note generator; reads immutable baseline/evaluation artifacts."""
import argparse
import csv
import json
from pathlib import Path
import sqlite3
import sys
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.pipeline import file_hash,write_once,canonical
from src.evaluate import FIELDS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--evaluation',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    header=json.loads((args.run/'run.json').read_text(encoding='utf-8'))
    evaluation=json.loads((args.evaluation/'summary.json').read_text(encoding='utf-8'))
    if (args.run/'active.lock').exists():raise ValueError('Run still active')
    rows=[s for s in evaluation['summaries'] if s['combination']['prompt']=='v1']
    if len(rows)!=4:raise ValueError('Expected four v1 comparison rows')
    rs=[json.loads(p.read_text(encoding='utf-8')) for p in args.run.glob('jobs/*/result.json')]
    out=root/'results/checkpoints/hw1_baseline_20261101'
    pre=json.loads((out/'preflight.json').read_text(encoding='utf-8'))
    smoke=json.loads((root/pre['provider_smoke_reference']).read_text(encoding='utf-8'))
    warm=json.loads((root/pre['local_warmup_reference']).read_text(encoding='utf-8'))
    with sqlite3.connect((root/'results/budget.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        accounted=db.execute('select sum(accounted) from charges').fetchone()[0]/1e9
    errors=[json.loads(l) for l in (args.evaluation/'disagreements.jsonl').read_text(encoding='utf-8').splitlines()]
    examples=[]
    for field in ['recommended_level','title','npcs','hook']:
        example=next((e for e in errors if e['combination']['prompt']=='v1' and e['observed_error']=='field_mismatch' and e['field']==field),None)
        if example:examples.append(example)
    failures=[{'text_id':r['identity']['text_id'],'provider':r['identity']['provider'],'sampling':r['identity']['sampling_name'],
               'failure':r['failure'],'actual_call_attempts':r['actual_call_attempts'],'latency_s':r['document_latency_s']} for r in rs if r['status']=='failed']
    complete=all(s['status']=='complete' for s in rows)
    summary={'kind':'hw1_v1_baseline_checkpoint','status':'complete_v1_only' if complete else 'blocked_or_incomplete',
        'run_reference':str(args.run),'evaluation_reference':str(args.evaluation),'evaluation_sha256':file_hash(args.evaluation/'summary.json'),
        'four_comparisons':rows,'initial_document_configurations_saved':len(rs),
        'actual_baseline_call_attempts':sum(r['actual_call_attempts'] for r in rs),
        'transport_retries':sum(r['transport_retry_count'] for r in rs),'repair_requests':sum(r['repair_count'] for r in rs),
        'failures':failures,'observed_disagreement_examples':examples,
        'causal_hypotheses':['Different selection of title/subtitle or strict whole-field wording may explain some mismatches; requires source review, not established causation.'],
        'cumulative_accounted_usd':accounted,'remaining_budget_usd':5-accounted,
        'actual_invoice_charge_usd':None,'v2_complete':False,'eight_row_final_comparison_complete':False}
    write_once(out/'summary.json',summary)
    with (args.evaluation/'field_metrics.csv').open(encoding='utf-8',newline='') as handle:
        reader=csv.DictReader(handle); fields=reader.fieldnames; metrics=[r for r in reader if r['prompt']=='v1']
    with (out/'field_metrics.csv').open('x',encoding='utf-8',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader();writer.writerows(metrics)
    with (out/'disagreements.jsonl').open('xb') as handle:
        for error in errors:
            if error['combination']['prompt']=='v1':handle.write(canonical(error)+b'\n')
    def number(v):return 'unknown' if v is None else f'{v:.4f}'
    lines=['# HW1 baseline checkpoint — 01.11.2026','',
        '**'+('v1 baseline виконано; v2 і фінальне eight-row comparison не виконані.' if complete else 'Baseline incomplete: див. counts і failures; v2 не виконано.')+'**','',
        'Це фактичні model calls, не mock measurements. Frozen inputs, prompts, schema та reviewed labels не змінювалися; reuse completed jobs: 0 (новий run).','',
        '## Перевірки та команди','',
        'Dataset: 30 nonempty texts (10 golden / 3 development / 17 corpus), 10/10 reviewed labels PASS, frozen snapshot hashes PASS, 125 tests PASS. Наявність OPENAI_API_KEY/PROVIDER_MODEL/LOCAL_MODEL/OLLAMA_BASE_URL перевірено без виводу credentials.','',
        '```powershell',
        '.\\.venv\\Scripts\\python.exe -X utf8 scripts/prepare_data.py validate --manifest data/ocr_revisions/windows-v1/manifest.jsonl',
        '.\\.venv\\Scripts\\python.exe -X utf8 scripts/validate_golden.py validate',
        '.\\.venv\\Scripts\\python.exe -m pytest -q',
        '.\\.venv\\Scripts\\python.exe main.py --dry-run --prompt v1',
        r'.\.venv\Scripts\python.exe -X utf8 scripts/checkpoint_smoke.py --provider openai',
        r'.\.venv\Scripts\python.exe -X utf8 scripts/checkpoint_smoke.py --provider ollama',
        '.\\.tools\\bin\\uv.exe run python -u main.py --prompt v1 --run-id '+header['run_id'],
        '.\\.tools\\bin\\uv.exe run python -m src.evaluate --run '+str(args.run)+' --output '+str(args.evaluation),
        '```','',
        'Для launcher commands використано repo-local `.tools/bin/uv.exe`; для validators/tests також прямо `.venv/Scripts/python.exe`. Це еквівалентні команди того самого isolated Python. Для повторного baseline не запускайте нові calls автоматично: `--resume '+header['run_id']+'` дозволяє reuse лише за повного identity match.','',
        '## Моделі та окремі smoke/warm-up','',
        'Requested provider: gpt-4o-mini; smoke returned gpt-4o-mini-2024-07-18. Responses API, strict JSON Schema, SDK retries=0. Каталог OpenAI позначає deprecated, але account access підтверджено реальним smoke. Заміни моделі немає.','',
        'Local: Ollama 0.40.13, qwen2.5:3b, 3.1B Q4_K_M; digest 357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b. Configured/loaded context 8192; native model metadata context 32768. GPU model/hardware cost не виміряно. Python 3.12.15; full package/runtime details у run.json.','',
        f"Provider smoke: schema-valid={smoke['schema_valid']}, latency {smoke['document_latency_s']:.4f}s, input/output {smoke['usage']['input_tokens']}/{smoke['usage']['output_tokens']}, tariff estimate ${smoke['cost']['estimated_usd']:.7f}.",
        f"Local warm-up: schema-valid={warm['schema_valid']}, latency {warm['document_latency_s']:.4f}s, input/output {warm['usage']['input_tokens']}/{warm['usage']['output_tokens']}, external API cost $0.",'',
        'Обидва виконані окремо, на першій повній development PDF-сторінці; вони не входять у 30-text metrics. Local warm-up повторив language=en для італійського source (очікується other), raw не виправляли. Попередній локальний smoke також збережено, не підмінено warm-up.','',
        'A: temperature=0.2/top_p=0.9; B: 0.8/0.9. Provider/local timeout 60/180 s; один transport retry на generation/repair, максимум один repair і чотири actual attempts/execution. Fixed repair_v1 для всіх prompts.','',
        '## Чотири фактичні comparison rows','',
        '| Model / sampling | Attempted / success / failed / missing / skipped | Mean field % | Populated % | First / final valid % | p50 / p95 seconds | Tariff USD | USD / 1000 attempted |',
        '|---|---|---:|---:|---|---|---:|---:|']
    for s in rows:
        c=s['combination'];n=s['counts'];l=s['latency']['all_attempted'];cost=s['cost']
        lines.append(f"| {c['model']} / {c['sampling']} | {n['attempted']} / {n['successful']} / {n['failed']} / {n['missing']} / {n['skipped']} | {100*s['mean_field_accuracy']:.2f} | {100*s['populated_field_accuracy']:.2f} | {s['first_pass_valid_pct']:.2f} / {s['final_valid_pct']:.2f} | {number(l['p50_s'])} / {number(l['p95_s'])} | {number(cost['tariff_equivalent_estimate_usd'])} | {number(cost['per_1000_attempted_texts_estimate_usd'])} |")
    lines += ['', 'Знаменники: кожний field — 10 golden, mean — 80 field cells, validity — 30 texts. Failure має 0/8 correct, навіть для empty golden fields. Whole-item sets/NPC pairs та normalized strings порівнюються за frozen rules; це exact field match, не часткова semantic accuracy. Percentiles: linear interpolation h=(n−1)p, type 7; latency включає retries/waits/repairs.','',
        '| Model / sampling | title | language | level | hook | npcs | locations | threats | rewards |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for s in rows:
        lines.append('| '+s['combination']['model']+' / '+s['combination']['sampling']+' | '+' | '.join(f'{100*v:.0f}%' for v in [s['field_accuracy'][f] for f in FIELDS])+' |')
    lines += ['', 'Failure-only latency (не виключено із загальної latency):','']
    for s in rows:
        l=s['latency']['failed'];lines.append(f"- {s['combination']['model']} / {s['combination']['sampling']}: n={l['n']}, p50={number(l['p50_s'])}, p95={number(l['p95_s'])}, unknown={l['unknown_count']}.")
    lines += ['', f"Збережено {len(rs)} terminal executions; actual baseline attempts={summary['actual_baseline_call_attempts']}, transport retries={summary['transport_retries']}, repair requests={summary['repair_requests']}. Failed examples не видаляли.",'',
        '## Бюджет та час','',
        'Офіційні [GPT-4o Mini prices](https://developers.openai.com/api/docs/models/gpt-4o-mini), повторно перевірено 01.11.2026: $0.15 uncached input / $0.075 cached input / $0.60 output за 1M tokens. Cached/thinking tokens не додаються повторно. Actual invoice/free-quota charges невідомі; estimates не означають actual списання коштів.','',
        f'Сукупний homework ledger (включно з provider smoke, усіма old/new recorded paid calls): ${accounted:.7f}; залишок ${5-accounted:.7f}. Локальний API $0; hardware/energy/runtime monetary cost unknown. Application estimates/reservations не гарантують final provider invoice.','',
        'Початковий rough provider estimate був ~$0.156 без retries; smoke-scaled runtime provider/local ~5.05/8.23 min був лише екстраполяцією короткої сторінки. Long texts і local timeouts зробили початкову local оцінку ненадійною. Фактична сума document timers:','']
    for provider in ['openai','ollama']:
        minutes=sum(r['document_latency_s'] for r in rs if r['identity']['provider']==provider)/60
        lines.append(f'- {provider}: {minutes:.2f} min (сума document-level end-to-end timers, не wall-clock setup).')
    lines += ['', '## Спостереження та issues','',
        'Повні failed artifacts і причини — checkpoint summary.json; raw attempts збережено в run directory. Для context failure server log evidence збережено окремо в local_context_evidence.txt. 8192 context не змінювали посеред baseline; silent truncation без server telemetry загалом не можна виключити.','',
        'Observed golden disagreements (це порівняння із frozen labels; не автоматичне встановлення, хто помилився):','']
    for e in examples:
        lines.append(f"- `{e['text_id']}`, {e['combination']['provider']}/{e['combination']['sampling']}, `{e['field']}`: golden `{json.dumps(e['expected'],ensure_ascii=False)}`; predicted `{json.dumps(e['predicted'],ensure_ascii=False)}`. Source/result/golden references збережено в checkpoint summary.json і disagreements.jsonl.")
    lines += ['', 'Causal hypotheses (не встановлені факти): різний вибір title/subtitle або source phrase formatting може пояснювати частину strict mismatches; потрібен ручний source review. Поточні labels не редагувалися. Hook/NPC/list exact-set mismatches також потребують source-level аналізу; валідний JSON не доводить фактологічну правильність.','',
        '## Готовність до course feedback','',
        'Готовий v1 baseline із реальними артефактами, fixed scoring, cost/runtime evidence та явними limitations. Це матеріал для feedback, а не доведений production choice. Відкриті питання: неоднозначність title/source phrase golden policy, строгість whole-field metrics, local context/output/timeout constraints.','',
        'Наступний крок: аналізувати development errors і підготувати обґрунтований v2 з changelog, не підлаштовувати prompt під held-out golden answers. Новий protocol/context експеримент тримати окремо. v2 та фінальне eight-row comparison ще не завершені.','',
        f'Artifacts: `{args.run}`, `{args.evaluation}`, `results/checkpoints/hw1_baseline_20261101/`.']
    note=root/'docs/HW1_BASELINE_CHECKPOINT.md'
    if note.exists():raise ValueError('Checkpoint note already exists; preserve history')
    note.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(f'Checkpoint: {summary["status"]}; note={note}')

if __name__=='__main__':main()
