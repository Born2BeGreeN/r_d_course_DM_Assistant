# HW1 baseline checkpoint — 01.11.2026

**v1 baseline виконано; v2 і фінальне eight-row comparison не виконані.**

Це фактичні model calls, не mock measurements. Frozen inputs, prompts, schema та reviewed labels не змінювалися; reuse completed jobs: 0 (новий run).

## Перевірки та команди

Dataset: 30 nonempty texts (10 golden / 3 development / 17 corpus), 10/10 reviewed labels PASS, frozen snapshot hashes PASS, 125 tests PASS. Наявність OPENAI_API_KEY/PROVIDER_MODEL/LOCAL_MODEL/OLLAMA_BASE_URL перевірено без виводу credentials.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/prepare_data.py validate --manifest data/ocr_revisions/windows-v1/manifest.jsonl
.\.venv\Scripts\python.exe -X utf8 scripts/validate_golden.py validate
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe main.py --dry-run --prompt v1
.\.venv\Scripts\python.exe -X utf8 scripts/checkpoint_smoke.py --provider openai
.\.venv\Scripts\python.exe -X utf8 scripts/checkpoint_smoke.py --provider ollama
.\.tools\bin\uv.exe run python -u main.py --prompt v1 --run-id hw1_baseline_20261101_v1_ab
.\.tools\bin\uv.exe run python -m src.evaluate --run results\runs\hw1_baseline_20261101_v1_ab --output results\evaluations\hw1_baseline_20261101_v1_ab
```

Для launcher commands використано repo-local `.tools/bin/uv.exe`; для validators/tests також прямо `.venv/Scripts/python.exe`. Це еквівалентні команди того самого isolated Python. Для повторного baseline не запускайте нові calls автоматично: `--resume hw1_baseline_20261101_v1_ab` дозволяє reuse лише за повного identity match.

## Моделі та окремі smoke/warm-up

Requested provider: gpt-4o-mini; smoke returned gpt-4o-mini-2024-07-18. Responses API, strict JSON Schema, SDK retries=0. Каталог OpenAI позначає deprecated, але account access підтверджено реальним smoke. Заміни моделі немає.

Local: Ollama 0.40.13, qwen2.5:3b, 3.1B Q4_K_M; digest 357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b. Configured/loaded context 8192; native model metadata context 32768. GPU model/hardware cost не виміряно. Python 3.12.15; full package/runtime details у run.json.

Provider smoke: schema-valid=True, latency 5.0470s, input/output 2320/173, tariff estimate $0.0004518.
Local warm-up: schema-valid=True, latency 8.2340s, input/output 1493/290, external API cost $0.

Обидва виконані окремо, на першій повній development PDF-сторінці; вони не входять у 30-text metrics. Local warm-up повторив language=en для італійського source (очікується other), raw не виправляли. Попередній локальний smoke також збережено, не підмінено warm-up.

A: temperature=0.2/top_p=0.9; B: 0.8/0.9. Provider/local timeout 60/180 s; один transport retry на generation/repair, максимум один repair і чотири actual attempts/execution. Fixed repair_v1 для всіх prompts.

## Чотири фактичні comparison rows

| Model / sampling | Attempted / success / failed / missing / skipped | Mean field % | Populated % | First / final valid % | p50 / p95 seconds | Tariff USD | USD / 1000 attempted |
|---|---|---:|---:|---|---|---:|---:|
| gpt-4o-mini / A | 30 / 30 / 0 / 0 / 0 | 28.75 | 29.03 | 100.00 / 100.00 | 3.0155 / 5.3362 | 0.0333 | 1.1114 |
| gpt-4o-mini / B | 30 / 30 / 0 / 0 / 0 | 28.75 | 29.03 | 100.00 / 100.00 | 2.8675 / 5.5623 | 0.0329 | 1.0981 |
| qwen2.5:3b / A | 30 / 27 / 3 / 0 / 0 | 18.75 | 24.19 | 90.00 / 90.00 | 41.0545 / 165.5284 | 0.0000 | 0.0000 |
| qwen2.5:3b / B | 30 / 28 / 2 / 0 / 0 | 20.00 | 25.81 | 93.33 / 93.33 | 30.9295 / 79.5702 | 0.0000 | 0.0000 |

Знаменники: кожний field — 10 golden, mean — 80 field cells, validity — 30 texts. Failure має 0/8 correct, навіть для empty golden fields. Whole-item sets/NPC pairs та normalized strings порівнюються за frozen rules; це exact field match, не часткова semantic accuracy. Percentiles: linear interpolation h=(n−1)p, type 7; latency включає retries/waits/repairs.

| Model / sampling | title | language | level | hook | npcs | locations | threats | rewards |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| gpt-4o-mini / A | 60% | 100% | 20% | 0% | 0% | 10% | 10% | 30% |
| gpt-4o-mini / B | 60% | 100% | 20% | 0% | 0% | 10% | 10% | 30% |
| qwen2.5:3b / A | 60% | 90% | 0% | 0% | 0% | 0% | 0% | 0% |
| qwen2.5:3b / B | 50% | 80% | 20% | 0% | 0% | 0% | 0% | 10% |

Failure-only latency (не виключено із загальної latency):

- gpt-4o-mini / A: n=0, p50=unknown, p95=unknown, unknown=0.
- gpt-4o-mini / B: n=0, p50=unknown, p95=unknown, unknown=0.
- qwen2.5:3b / A: n=3, p50=246.4370, p95=351.4283, unknown=0.
- qwen2.5:3b / B: n=2, p50=54.3120, p95=61.6668, unknown=0.

Збережено 120 terminal executions; actual baseline attempts=123, transport retries=3, repair requests=0. Failed examples не видаляли.

## Бюджет та час

Офіційні [GPT-4o Mini prices](https://developers.openai.com/api/docs/models/gpt-4o-mini), повторно перевірено 01.11.2026: $0.15 uncached input / $0.075 cached input / $0.60 output за 1M tokens. Cached/thinking tokens не додаються повторно. Actual invoice/free-quota charges невідомі; estimates не означають actual списання коштів.

Сукупний homework ledger (включно з provider smoke, усіма old/new recorded paid calls): $0.0667380; залишок $4.9332620. Локальний API $0; hardware/energy/runtime monetary cost unknown. Application estimates/reservations не гарантують final provider invoice.

Початковий rough provider estimate був ~$0.156 без retries; smoke-scaled runtime provider/local ~5.05/8.23 min був лише екстраполяцією короткої сторінки. Long texts і local timeouts зробили початкову local оцінку ненадійною. Фактична сума document timers:

- openai: 3.28 min (сума document-level end-to-end timers, не wall-clock setup).
- ollama: 50.06 min (сума document-level end-to-end timers, не wall-clock setup).

## Спостереження та issues

Повні failed artifacts і причини — checkpoint summary.json; raw attempts збережено в run directory. Для context failure server log evidence збережено окремо в local_context_evidence.txt. 8192 context не змінювали посеред baseline; silent truncation без server telemetry загалом не можна виключити.

Observed golden disagreements (це порівняння із frozen labels; не автоматичне встановлення, хто помилився):

- `pdf_090c3a438c6f390a53ad_p001-007`, openai/A, `recommended_level`: golden `"1-2"`; predicted `"level 1 - 2"`. Source/result/golden references збережено в checkpoint summary.json і disagreements.jsonl.
- `pdf_f72f9d30936a1f7366c8_p001-004`, openai/A, `title`: golden `"Book Wyrm’s Birthday Gift"`; predicted `"Wyrm’s Birthday Gift"`. Source/result/golden references збережено в checkpoint summary.json і disagreements.jsonl.
- `pdf_090c3a438c6f390a53ad_p001-007`, openai/A, `npcs`: golden `[{"name": "The Great Pumpkin", "role": "villain"}]`; predicted `[{"name": "The Great Pumpkin", "role": "Demonic Construct, Chaotic Evil"}, {"name": "Pumpkids", "role": "Small Demonic Undead"}]`. Source/result/golden references збережено в checkpoint summary.json і disagreements.jsonl.
- `pdf_090c3a438c6f390a53ad_p001-007`, openai/A, `hook`: golden `"The small farming village of Krahedorf, if you can call their meager corn crops “farms”, hashad a rash of children go missing leading up to all hallows eve"`; predicted `"The villagers tell you a tale of how their children have got missing and they suspect 'The Great Pumpkin' has lured the children to the cornfields with promises of treats and gifts."`. Source/result/golden references збережено в checkpoint summary.json і disagreements.jsonl.

Causal hypotheses (не встановлені факти): різний вибір title/subtitle або source phrase formatting може пояснювати частину strict mismatches; потрібен ручний source review. Поточні labels не редагувалися. Hook/NPC/list exact-set mismatches також потребують source-level аналізу; валідний JSON не доводить фактологічну правильність.

## Готовність до course feedback

Готовий v1 baseline із реальними артефактами, fixed scoring, cost/runtime evidence та явними limitations. Це матеріал для feedback, а не доведений production choice. Відкриті питання: неоднозначність title/source phrase golden policy, строгість whole-field metrics, local context/output/timeout constraints.

Наступний крок: аналізувати development errors і підготувати обґрунтований v2 з changelog, не підлаштовувати prompt під held-out golden answers. Новий protocol/context експеримент тримати окремо. v2 та фінальне eight-row comparison ще не завершені.

Artifacts: `results\runs\hw1_baseline_20261101_v1_ab`, `results\evaluations\hw1_baseline_20261101_v1_ab`, `results/checkpoints/hw1_baseline_20261101/`.
