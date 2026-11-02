"""Offline evaluation only: saved pipeline evidence against reviewed golden cards."""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import itertools
import json
import math
from pathlib import Path
import sys
import uuid

from src.budget import NANO, price_usage
from src.pipeline import ExperimentConfig, canonical, file_hash, fingerprint, write_once, card_validation
from src.schema import AdventureCard, card_json_schema

FIELDS = tuple(AdventureCard.model_fields)
RULES = {
    'version': 'hw1-exact-fields-v1',
    'strings': 'str.casefold and whitespace collapse only; punctuation/accents preserved',
    'lists': 'exact normalized full-item sets; order and duplicate multiplicity ignored',
    'npcs': 'sets of normalized (name, role) pairs; null role distinct from empty string',
    'enum_null': 'exact', 'failed_missing_skipped': 'all eight fields incorrect',
    'percentile': 'linear interpolation, h=(n-1)*p (Hyndman-Fan type 7)',
}


def normalized(value):
    return ' '.join(value.split()).casefold() if isinstance(value, str) else value


def field_equal(field, expected, actual):
    if expected is None or actual is None or field == 'language':
        return type(expected) is type(actual) and expected == actual
    if field == 'npcs':
        return {(normalized(n['name']), normalized(n['role'])) for n in expected} == {(normalized(n['name']), normalized(n['role'])) for n in actual}
    if isinstance(expected, list):
        return {normalized(v) for v in expected} == {normalized(v) for v in actual}
    return normalized(expected) == normalized(actual)


def percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    h = (len(values)-1)*p
    lo, hi = math.floor(h), math.ceil(h)
    return values[lo] + (values[hi]-values[lo])*(h-lo)


def latency_stats(records):
    values = [r['latency_s'] for r in records if r.get('latency_s') is not None]
    return {'n':len(values), 'unknown_count':len(records)-len(values), 'p50_s':percentile(values,.5), 'p95_s':percentile(values,.95)}


def summarize(records, inputs, golden, combo):
    """Pure scoring core; records keyed by text ID, including partial/skipped evidence."""
    counts = dict(attempted=0,successful=0,failed=0,missing=0,skipped=0,partial=0)
    correct = dict.fromkeys(FIELDS,0)
    populated_correct = populated_total = 0
    disagreements = []
    first = final = calls = 0
    costs = []
    attempted_records = []
    for text_id, source in inputs.items():
        record = records.get(text_id)
        state = record['state'] if record else 'missing'
        if state == 'skipped':
            counts['skipped'] += 1
        elif record and record.get('attempted'):
            counts['attempted'] += 1
            attempted_records.append(record)
            counts['successful' if state == 'successful' else 'failed'] += 1
            counts['partial'] += int(state == 'partial')
        else:
            counts['missing'] += 1
        valid = bool(record and state == 'successful')
        first += int(bool(record and record.get('first_pass_valid')))
        final += int(valid)
        if record:
            calls += record.get('actual_calls',0)
            costs.extend(record.get('call_costs',[]))
        if text_id not in golden:
            continue
        label = golden[text_id]
        for field in FIELDS:
            expected = label['card'][field]
            predicted = record['card'][field] if valid else None
            equal = valid and field_equal(field,expected,predicted)
            correct[field] += int(equal)
            populated = expected is not None and expected != [] and expected != ''
            populated_total += int(populated)
            populated_correct += int(equal and populated)
            if not equal:
                disagreements.append({'text_id':text_id,'field':field,'expected':expected,'predicted':predicted,
                    'observed_error': 'field_mismatch' if valid else state,
                    'causal_hypotheses':[], 'source_reference':source,'golden_reference':label['reference'],
                    'result_reference':record.get('reference') if record else None})
    local = combo['provider'] == 'ollama'
    unknown = sum(v is None for v in costs)
    known_cost = sum(v for v in costs if v is not None)
    total = 0. if local else None if unknown else known_cost
    complete = counts['attempted'] == len(inputs) and counts['partial'] == 0
    summary = {'combination':combo, 'status':'complete' if complete else 'incomplete', 'counts':counts,
        'field_accuracy':{f:correct[f]/len(golden) for f in FIELDS},
        'mean_field_accuracy':sum(correct.values())/(len(golden)*len(FIELDS)),
        'populated_field_accuracy':populated_correct/populated_total if populated_total else None,
        'populated_correct':populated_correct,'populated_denominator':populated_total,
        'golden_denominator':len(golden),'validity_denominator':len(inputs),
        'first_pass_valid_pct':100*first/len(inputs),'final_valid_pct':100*final/len(inputs),
        'latency':{'method':RULES['percentile'],'all_attempted':latency_stats(attempted_records),
                   'successful':latency_stats([r for r in attempted_records if r['state']=='successful']),
                   'failed':latency_stats([r for r in attempted_records if r['state']!='successful'])},
        'cost':{'actual_call_attempts':calls,
                'unknown_dispatch_attempts':sum(r.get('unknown_dispatches',0) for r in records.values()),
                'scope':'saved attempted texts only; missing/skipped texts have no measured cost; not a completed-corpus projection','tariff_equivalent_estimate_usd':total,
                'known_tariff_subtotal_usd':0. if local else known_cost,'unknown_cost_attempts':0 if local else unknown,
                'per_1000_attempted_texts_estimate_usd':1000*total/counts['attempted'] if total is not None and counts['attempted'] else None,
                'actual_provider_charge_usd':0. if local or not calls else None,
                'free_quota_status':'not_applicable_local' if local else 'unknown_not_inferred_from_tariff',
                'hardware_cost_usd':None,'runtime_cost_usd':None}}
    return summary, disagreements


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def checked_path(base, relative):
    p = (base / relative).resolve()
    if not p.is_relative_to(base.resolve()):
        raise ValueError('Artifact path escapes root')
    return p


def read_job(directory, identity):
    result_path = directory/'result.json'
    result = None
    if result_path.exists():
        if (directory/'result.sha256').read_text().strip() != file_hash(result_path):
            raise ValueError(f'Result checksum mismatch: {result_path}')
        result = read_json(result_path)
        expected = dict(result['identity']); expected.pop('request_contract',None)
        if expected != identity or fingerprint(result['identity']) != result['identity_sha256']:
            raise ValueError(f'Result identity mismatch: {result_path}')
        contract = result['identity']['request_contract']
        for key,value in {'input_sha256':identity['input_sha256'],'prompt_sha256':identity['prompt_sha256'],
                          'schema_sha256':identity['protocol']['schema_sha256'],'sampling':identity['sampling'],
                          'operations':identity['protocol']['config']['operations'],'provider':identity['provider'],
                          'repair_prompt_sha256':identity['protocol']['repair_prompt_sha256']}.items():
            if contract.get(key) != value:
                raise ValueError(f'Request contract mismatch: {result_path}: {key}')
        for attempt in result['attempts']:
            for prefix in ('intent','response','validation'):
                if attempt.get(prefix+'_path') and file_hash(checked_path(directory,attempt[prefix+'_path'])) != attempt[prefix+'_sha256']:
                    raise ValueError(f'Attempt checksum mismatch: {directory}')
    intents = sorted(directory.glob('attempt_*.intent.json'))
    if not intents and result is None:
        return None
    costs, calls, unknown_dispatches = [], 0, 0
    responses = []
    for path in intents:
        intent = read_json(path)
        response_path = path.with_name(path.name.replace('.intent.json','.response.json'))
        response = read_json(response_path)['response'] if response_path.exists() else None
        n = response['metadata'].get('sdk_call_count',response['metadata'].get('http_attempts',1)) if response else 1
        if type(n) is not int or n not in (0,1):
            raise ValueError(f'Unaccounted hidden retries: {path}')
        calls += n
        unknown_dispatches += int(response is None)
        if response:
            responses.append((intent['stage'],response))
        if intent['provider'] != identity['provider']:
            raise ValueError(f'Attempt provider mismatch: {path}')
        if n:
            if identity['provider'] == 'ollama':
                costs.append(0.)
            else:
                profile = intent['pricing']
                model = (response.get('returned_model') or response['requested_model']) if response else None
                value = price_usage(response['usage'],profile) if response and model in profile['model_ids'] else None
                costs.append(value/NANO if value is not None else None)
    if result and calls != result['actual_call_attempts']:
        raise ValueError(f'Attempt count mismatch: {result_path}')
    valid = bool(result and result['status']=='succeeded' and result['final_valid'])
    if result:
        generation = [r for stage,r in responses if stage == 'generation']
        last = responses[-1][1] if responses else None
        def response_valid(r):
            return bool(r and not r.get('error') and r['finish_status'] in ('completed','stop') and not r['metadata'].get('refusals') and not r['metadata'].get('provider_error') and card_validation(r['raw_text'])[0] is not None)
        first_valid = response_valid(generation[-1] if generation else None)
        if first_valid != result['first_pass_valid'] or valid != bool(result['final_valid']):
            raise ValueError(f'Schema validity evidence mismatch: {result_path}')
        if valid and (not response_valid(last) or card_validation(last['raw_text'])[0] != result['final_card']):
            raise ValueError(f'Final card differs from raw response: {result_path}')
    card = AdventureCard.model_validate(result['final_card']).model_dump(mode='json') if valid else None
    latency = result['document_latency_s'] if result else None
    if latency is not None and (not isinstance(latency,(int,float)) or not math.isfinite(latency) or latency<0):
        raise ValueError(f'Invalid latency: {result_path}')
    return {'state':'successful' if valid else 'skipped' if result and calls==0 else 'failed' if result else 'partial', 'attempted':calls>0,
            'first_pass_valid':bool(result and result['first_pass_valid']), 'card':card,'latency_s':latency,
            'actual_calls':calls,'unknown_dispatches':unknown_dispatches,'call_costs':costs,'reference':str(result_path if result else directory)}


def evaluate(root, config_path, run_dirs, output):
    # Reuse the read-only frozen-input/golden gate; never construct an adapter.
    from main import frozen_inputs
    cfg = ExperimentConfig.model_validate_json(config_path.read_text(encoding='utf-8'))
    items, frozen = frozen_inputs(root,cfg)
    inputs = {r['text_id']:r for r in frozen['inputs']}
    golden = {r['text_id']:{'card':AdventureCard.model_validate(read_json(root/r['annotation_path'])).model_dump(mode='json'),
                          'reference':r['annotation_path']} for r in frozen['annotations']}
    combinations = {(p,v,s):{'provider':p,'model':cfg.models[p],'prompt':v,'sampling':s}
                    for p,v,s in itertools.product(cfg.models,cfg.prompts,cfg.sampling)}
    records = {key:{} for key in combinations}
    selected = {key:set() for key in combinations}
    common = None
    evidence = []
    for run_dir in run_dirs:
        if (run_dir/'active.lock').exists():
            raise ValueError(f'Run still active or unreconciled: {run_dir}')
        header_path = run_dir/'run.json'; header = read_json(header_path)
        protocol = header['protocol']
        if protocol['evaluation_snapshot_sha256'] != file_hash(root/cfg.evaluation_snapshot) or protocol['schema_sha256'] != fingerprint(card_json_schema()):
            raise ValueError(f'Incompatible evaluation snapshot/schema: {run_dir}')
        if protocol['dataset_descriptor_sha256'] != file_hash(root/cfg.dataset_descriptor) or protocol['repair_prompt_sha256'] != file_hash(root/cfg.repair_prompt):
            raise ValueError(f'Incompatible dataset/repair contract: {run_dir}')
        if protocol['config'] != cfg.model_dump(mode='json'):
            raise ValueError(f'Incompatible configuration: {run_dir}')
        if common is not None and common != protocol:
            raise ValueError('Runs have incompatible code/settings/runtime/prompt contracts; evaluate separately')
        common = protocol
        if fingerprint([j['job_id'] for j in header['jobs']]) != header['run_identity_sha256']:
            raise ValueError(f'Invalid run identity: {run_dir}')
        evidence.append({'path':str(header_path),'sha256':file_hash(header_path)})
        for job in header['jobs']:
            identity=job['identity']; tid=identity['text_id']
            key=(identity['provider'],identity['prompt_version'],identity['sampling_name'])
            if fingerprint(identity)!=job['job_id'] or identity['protocol']!=protocol or tid not in inputs or identity['input_sha256']!=inputs[tid]['text_sha256'] or identity['split']!=inputs[tid]['split']:
                raise ValueError(f'Incompatible job/input: {run_dir}')
            if identity['sampling'] != dict(cfg.sampling[key[2]],max_output_tokens=cfg.operations.max_output_tokens) or identity['model']!=protocol['models'][key[0]]:
                raise ValueError('Incompatible model/sampling')
            if identity['prompt_sha256'] != file_hash(root/cfg.prompts[key[1]]):
                raise ValueError('Prompt hash changed; evaluate with original configuration/files')
            if tid in selected[key]:
                raise ValueError('Overlapping executions would bias comparison; evaluate repeated runs separately')
            selected[key].add(tid)
            combinations[key]['model']=identity['model']
            record=read_job(run_dir/'jobs'/job['job_id'],identity)
            if record:
                records[key][tid]=record
    summaries, disagreements = [], []
    for key,combo in combinations.items():
        if selected[key]:
            for tid in inputs.keys()-selected[key]:
                records[key][tid]={'state':'skipped','attempted':False}
        summary, errors=summarize(records[key],inputs,golden,combo)
        summaries.append(summary)
        disagreements.extend(dict(error,combination=combo) for error in errors)
    output.mkdir(parents=True,exist_ok=False)
    write_once(output/'summary.json',{'rules':RULES,'status':'complete' if all(s['status']=='complete' for s in summaries) else 'incomplete',
        'evaluation_code_sha256':file_hash(Path(__file__)), 'evaluation_snapshot_sha256':file_hash(root/cfg.evaluation_snapshot),
        'run_evidence':evidence,'excluded_smoke':'Smoke excerpts are not benchmark inputs and are never scored.',
        'summaries':summaries})
    with (output/'field_metrics.csv').open('x',encoding='utf-8',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['provider','model','prompt','sampling','field','correct','denominator','accuracy','status'])
        writer.writeheader()
        for s in summaries:
            for field,accuracy in s['field_accuracy'].items():
                writer.writerow(dict(s['combination'],field=field,correct=round(accuracy*len(golden)),denominator=len(golden),accuracy=accuracy,status=s['status']))
    with (output/'disagreements.jsonl').open('xb') as handle:
        for error in disagreements:
            handle.write(canonical(error)+b'\n')
    lines=['# Offline evaluation','', 'Status: '+('complete' if all(s['status']=='complete' for s in summaries) else 'incomplete'), '', 'No model calls. Smoke excluded. Missing/skipped/failed golden fields count as incorrect.', '', '| Provider / model | Prompt | Sampling | Status | Attempted | Success | Failed | Missing | Skipped | Mean field accuracy |', '|---|---|---|---|---:|---:|---:|---:|---:|---:|']
    for s in summaries:
        c=s['combination']; n=s['counts']
        lines.append(f"| {c['provider']} / {c['model']} | {c['prompt']} | {c['sampling']} | {s['status']} | {n['attempted']} | {n['successful']} | {n['failed']} | {n['missing']} | {n['skipped']} | {s['mean_field_accuracy']:.4f} |")
    lines.extend(['', 'Unmeasured combinations have zero correct fields on fixed denominators; these are coverage penalties, not observed model accuracy.', '', 'Percentiles: '+RULES['percentile']+'. Missing durations are unknown, never zero. Details, costs and failure-only latency: summary.json.'])
    (output/'SUMMARY.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(f'Offline evaluation: {len(run_dirs)} saved runs; {len(summaries)} combinations; output={output}; model calls=0')
    return summaries


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='config.json')
    parser.add_argument('--run',action='append',type=Path,help='Saved run directory; repeat only for disjoint compatible jobs')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    dirs=args.run if args.run is not None else sorted((root/'results/runs').glob('*/run.json'))
    if args.run is None:
        dirs=[p.parent for p in dirs]
    output=args.output or root/'results/evaluations'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid.uuid4().hex[:8])
    try:
        evaluate(root,root/args.config,dirs,output)
        return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(f'Offline evaluation stopped: {exc}',file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
