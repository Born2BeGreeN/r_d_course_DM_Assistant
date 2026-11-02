# Послідовний pipeline HW1

`main.py`, `src/pipeline.py`, `src/budget.py` та `config.json` реалізують виконання через наявні адаптери. Вимоги курсу — порівняння моделей/prompts/sampling, validation і бюджет USD 5; SQLite ledger, checksum sidecars, послідовний CLI та наведені deadlines — наші реалізаційні рішення.

## Команди PowerShell

Після setup стандартна фінальна команда:

```powershell
uv run python main.py
```

Це **30 texts × OpenAI/Ollama × v1/v2 × A/B = 240** початкових extraction executions. Retries/repair додають спроби, максимум чотири на execution. Відсутній prompt, модель, service, ключ або frozen artifact спричиняє явну помилку; матриця не зменшується автоматично.

Без генерацій, мережевих probes чи запису результатів/ledger:

```powershell
uv run python main.py --dry-run
uv run python main.py --dry-run --prompt v1
```

Наразі перша команда повертає exit 2 через відсутній `prompts/v2.txt`, залишаючи planned count 240. Друга проходить і показує 120 executions. v2 ще потребує окремого обґрунтованого створення та changelog; pipeline не підміняє його копією v1. Реальні provider smoke, local warm-up та повний v1 baseline виконані 01.11.2026: див. [checkpoint](HW1_BASELINE_CHECKPOINT.md). OpenAI account access підтверджено запитами; v2 залишається відсутнім. Попередні blocked reports збережено як історію.

Селектори для майбутнього явно дозволеного запуску:

```powershell
uv run python main.py --provider openai --prompt v1 --sampling A --text EXACT_TEXT_ID --run-id experiment_01
uv run python main.py --provider openai --prompt v1 --sampling A --text EXACT_TEXT_ID --resume experiment_01
uv run python main.py --config config.json --dry-run
uv run python -m pytest -q
```

`--text` можна повторювати. Default selectors — all. Без `--run-id` створюється UTC timestamp + UUID. Для resume повторіть ті самі selectors/config; повний identity включає вхід, schema, prompts/repair, sampling, models, operations, ціни, frozen snapshot, code/uv.lock, Python/packages та local runtime/digest. Зміна identity блокує reuse. Terminal result та кожний intent/raw/validation перевіряються hashes. Partial/in-flight jobs і залишений після crash `active.lock` потребують ручного аудиту, щоб не повторити потенційно оплачений запит. Не видаляйте lock до перевірки, що процес завершився; не редагуйте історичні артефакти для обходу gate.

## Налаштування та evidence

Pipeline бере operations і A/B з `config.json`: A = temperature 0.2/top_p 0.9, B = 0.8/0.9. Provider/local timeouts — 60/180 s; deadline на logical generation або repair — 150/390 s; Retry-After bounded 30 s. Ці operations мають пріоритет над standalone Ollama environment defaults. Моделі можна задати `PROVIDER_MODEL`, `LOCAL_MODEL`; ключ — `OPENAI_API_KEY`, адреса локального service — `OLLAMA_BASE_URL`. Ключі не зберігаються в результатах. Інший зовнішній model ID без перевіреного pricing profile відхиляється.

Кожен logical request має максимум один transport retry; schema-invalid generation має максимум один repair request, теж із максимум одним transport retry. Є спільна межа чотири actual attempts. SDK та HTTP retries вимкнені. Transient transport failure не запускає schema repair. Credentials/global configuration/quota failures зупиняють batch. Retry-After seconds/HTTP-date враховується повністю; якщо затримка перевищує bound або remaining deadline, retry скасовується. Deadline обмежує dispatch/waits і timeout наступного виклику; синхронні SDK HTTP timeouts не гарантують жорстке скасування серверної роботи точно в цю секунду. Невідомі timeout charges залишаються зарезервованими.

`prompts/repair_v1.txt` незмінно спільний для extraction prompt versions. Repair отримує source text, invalid answer, validation errors; API отримує ту саму JSON Schema. Обидві моделі отримують ті самі finalized source text та extraction instructions. Provenance та execution metadata залишаються поза карткою.

У `results/runs/<run_id>/` зберігаються immutable `run.json`, job directories та окремі summaries. До виклику пишеться intent, після виклику — exact raw response і usage **перед validation**, далі validation sidecar, terminal result та checksum. Result містить first-pass/final validity, retry/repair counts, всі спроби, final card/null, latency, usage та estimated/unknown cost. First-pass означає initial logical generation після можливого transport retry, до repair. Tests використовують лише synthetic fixtures і тимчасові каталоги, не справжні results.

## Ціни та сукупний бюджет

Офіційні [GPT-4o Mini model/pricing docs](https://developers.openai.com/api/docs/models/gpt-4o-mini), перевірено **2026-11-01**: standard text ціни за 1M tokens — input **$0.15**, cached input **$0.075**, output **$0.60**. Каталог позначає модель deprecated; автоматичної заміни немає, account availability невідома. Перед майбутнім live use слід повторно перевірити доступність/актуальність ціни. Config фіксує дату та джерело. Cached tokens — частина input, reasoning/thinking — частина output; їх не додають повторно. Окремої thinking/cache-write ставки для вибраної моделі не заявлено. За відсутності cache counters використовується uncached upper estimate.

`results/budget.sqlite3` — спільний для всіх runs, smoke, retries та repairs ledger із атомарним reservation **перед кожною оплачуваною спробою**. Audit читає також historical JSON results, call intents та `results/budget_adjustments/`; charge IDs не рахуються повторно. Unknown historical external calls без достатніх даних блокують повні $5 до ручного аудиту. Непрочитаний historical JSON зупиняє аудит, а не вважається нульовою витратою. Зберігайте ledger разом із history.

Для поточної моделі reservation використовує весь context 128000 uncached input tokens + output cap 2048: **$0.0204288 за спробу**, незалежно від довжини джерела. Known usage звільняє надлишковий reserve; unknown usage/crash зберігає conservative hold. Unknown cost позначається null, окремо записується accounted reservation. Ціна локальної енергії невідома; зовнішній API cost локальних викликів нульовий. Ця реалізація не заявляє виміряні benchmark costs.

Початкове `prior_spend_usd=0` відображає відсутність recorded external generation calls у перевіреній історії репозиторію. Витрати поза репозиторієм неможливо автоматично встановити: внесіть їх у prior_spend з новим унікальним reference до запуску; reference незмінно зберігається в budget_adjustments. Не дублюйте витрати, вже імпортовані з raw results. Ledger забороняє нову спробу, якщо сукупні estimates/reservations перевищили б $5. **Оцінки застосунку не гарантують остаточний рахунок провайдера**: існують зовнішні витрати, зміни тарифів і невідомий usage. Для фінального звірення потрібні provider billing дані.

## Фінальний стан — 01.11.2026

V2 тепер існує; історичний missing-v2 blocker вище знято. Фінальна матриця — 240 terminal records із двох disjoint compatible runs, без rerun matching v1. [REPORT.md](../REPORT.md) містить усі вісім rows. Для повторного аналізу використовуйте offline `python -m src.evaluate --run results/runs/hw1_baseline_20261101_v1_ab --run results/runs/hw1_final_20261101_v2_ab`; запуск нового `main.py` без resume є новим generation run і не потрібний для оновлення timestamps. Prompt file bytes та effective submitted text hashes збережено окремо; offline checker враховує universal newline decoding без зміни prompts чи measurements.