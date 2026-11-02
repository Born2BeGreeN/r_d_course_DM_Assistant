# Offline evaluation

`src/evaluate.py` читає лише збережені pipeline results і reviewed golden labels. Він не створює адаптерів, не перевіряє service availability, не завантажує credentials та не викликає модель. Поточні frozen schema/input/annotation hashes і completion gate перевіряються до оцінювання. Golden JSON не редагуються.

## Зафіксовані comparison rules

Версія `hw1-exact-fields-v1` записується в кожний `summary.json` разом із hash evaluator code.

- Рядки: лише collapse whitespace та `casefold()`. Пунктуація, діакритика й формулювання лишаються значущими; synonyms/fuzzy/substring matching немає.
- Lists: повна рівність множин normalized items. Порядок і повторення однакового item не впливають; часткового кредиту немає.
- NPCs: множини normalized `(name, role)` pairs. Null role відрізняється від порожнього рядка; ролі не ігноруються.
- Language enum і null: exact comparison.
- Failed/partial/missing/skipped extraction: **усі вісім полів incorrect**, зокрема якщо golden field null або [].

Для кожного model/prompt/sampling знаменник field accuracy завжди **10 golden**. Mean field accuracy — середнє восьми field accuracies (еквівалент correct/80). Populated-field accuracy має знаменник усіх golden field cells, крім null, [] та порожнього рядка; language enum включений. Відсутні результати не видаляються зі знаменників. Для unmeasured combination нульові correct counts — coverage penalty, а не виміряна якість моделі; status incomplete.

First-pass/final validity — percentages із знаменником **30**, незалежно від наявності збережених outputs. First-pass — initial logical generation після transport retry, до repair. Успіх вимагає terminal successful record, final validity і schema-valid card, що відповідає raw response. Saved validity flags звіряються з raw response evidence.

## Offline команда

```powershell
uv run python -m src.evaluate
```

За замовчуванням беруться всі `results/runs/*/run.json`. Вихід — новий унікальний `results/evaluations/<UTC_UUID>/`; історія не перезаписується. Відсутність benchmark runs дає явний incomplete report на всі 8 combinations із 30 missing у кожній. Smoke excerpt не є одним із benchmark inputs і не включається в metrics. Нормальне створення incomplete report має exit 0; incompatible/corrupt artifacts — exit 2.

Для окремого run або disjoint compatible partial runs:

```powershell
uv run python -m src.evaluate --run results/runs/RUN_ID
uv run python -m src.evaluate --run results/runs/PART_1 --run results/runs/PART_2 --output results/evaluations/COMPARISON_ID
uv run python -m pytest -q tests/test_evaluate.py
```

Для повторної оцінки задайте новий output directory. Повторні незалежні виконання одного text/combo не змішуються: overlapping IDs відхиляються, навіть якщо одне виконання було failed. Порівнюйте такі runs окремими командами. Active/in-flight lock блокує evaluation до ручного reconciliation; partial artifacts без active lock відображаються як incomplete.

Сумісність перевіряється за frozen evaluation snapshot/schema/dataset, повним saved protocol (configuration, code, dependencies, operations, pricing, repair, runtime), job/input/prompt hashes, моделлю та sampling. Result checksum і checksums intent/raw/validation звіряються; зміни контрактів потребують окремих reports. Current code не мусить збігатися зі старим generation code: потрібна рівність saved generation protocols між об'єднуваними runs. Extraction prompt і repair files мають відповідати saved hashes. Немає вибору лише найкращого result чи автоматичного merge несумісних runs.

## Counts, latency, cost

`attempted` — кількість texts із принаймні однією actual/possibly dispatched attempt; successful і failed ділять attempted texts, partial є підмножиною failed. `missing` — текст очікується, але немає attempt evidence. `skipped` — явно не включений text у partial selection або terminal job, який зупинився до actual call. За повної відсутності runs це missing, не skipped. `attempted + missing + skipped = 30`. Complete означає 30 attempted і відсутність partial jobs; failed terminal extraction не приховується і не робить виконаний run incomplete.

Latency береться з document-level pipeline timer: включає retries, waits, repairs і persistence усередині pipeline. p50/p95 подано для всіх attempted, окремо successful та failed; percentile method — **linear interpolation, h=(n−1)p, Hyndman–Fan type 7**. Missing duration — null/unknown_count; її не замінюють нулем. Partial execution без terminal timing не входить у latency quantile, але залишається failed і unknown latency count. Невиміряні тексти не мають вигаданої latency.

External tariff-equivalent estimate підсумовує usage **кожного** raw attempt за його збереженим pricing profile, включно з transport failures, retries та repairs. Cached input і reasoning/output не рахуються повторно. `cost per 1000 = total estimate / attempted texts × 1000`. Якщо будь-яка оплачувана attempt не має достатнього usage/model pricing, total/per-1000 лишаються null, а known subtotal та unknown_cost_attempts подаються окремо. Conservative budget reservations не видаються за actual charge.

Intent без response вважається potentially dispatched: unknown_dispatch_attempts явно позначає невизначеність лічильника, зовнішня вартість невідома. No-call adapter record не оплачується. Missing/skipped texts не мають виміряних витрат; report costs стосуються лише saved attempted texts, це не прогноз повного corpus run. За нульових calls recorded tariff subtotal 0, per-1000 null, status incomplete.

Actual provider bill/free-quota charge **невідомий**, якщо є external calls: usage×tariff не доводить списання коштів чи безкоштовність. Local API cost — **0**, hardware/runtime monetary cost — **unknown**, latency подається окремо. Цей evaluator не змінює бюджетний ledger, не заявляє invoice reconciliation та не включає smoke у benchmark cost; cumulative homework budget продовжує враховувати smoke через pipeline budget audit.

## Артефакти

- `summary.json`: rules, evaluator/snapshot hashes, run header references/hashes, усі metrics та completeness.
- `SUMMARY.md`: коротка таблиця восьми combinations і coverage.
- `field_metrics.csv`: 8 fields × 8 combinations із numerator/denominator/status.
- `disagreements.jsonl`: field-level expected/predicted values, source text/PDF provenance, golden/result references, observed mismatch або missing/failed/skipped state. `causal_hypotheses` лишаються порожніми: evaluator не виводить причини з самого факту помилки й не вигадує model explanations.

Початковий offline запуск без benchmark data збережено як історію. Після реального [v1 checkpoint](HW1_BASELINE_CHECKPOINT.md) є чотири complete v1 combinations, усі 30 attempted у кожній; v2 лишається incomplete. Повний evaluator report: `results/evaluations/hw1_baseline_20261101_v1_ab/`; v1-only summary/CSV/disagreements: `results/checkpoints/hw1_baseline_20261101/`. Цей baseline не завершує фінальне eight-row comparison і не доводить production choice.

## Фінальний експеримент — 01.11.2026

Сумісний набір `hw1_baseline_20261101_v1_ab` + `hw1_final_20261101_v2_ab` містить **240 unique initial/terminal records**, вісім complete rows із 30 attempted; 229 schema-valid, 11 failed, missing/skipped 0. [Фінальний звіт](../REPORT.md), metrics у `results/evaluations/hw1_final_20261101/`, metadata/audit у `results/final/hw1_20261101/`. Попередні incomplete evaluations збережено як історію.

До фінального порівняння виправлено тільки offline compatibility check: raw prompt file hash і effective UTF-8 submitted-text hash можуть відрізнятися через `Path.read_text` universal newline decoding (v2 має CRLF). Artifact byte hash надалі перевіряється за saved identity; request contract перевіряється за точним text hash, який реально формував `main.py`. Prompt/repair bytes, source inputs і saved records не змінюються. Старий evaluator збережено як `evaluator_before_newline_fix.py`, old/new hashes — в `evaluator_compatibility_fix.json`; regression tests охоплюють LF/CRLF та rejection неправильного effective hash. AST scoring functions і comparison rules незмінні; однаковий evaluator застосовано до всіх восьми rows. Це не підстава повторно запускати measurements.