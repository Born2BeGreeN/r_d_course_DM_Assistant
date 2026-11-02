# Adventure Assistant — Homework 1

Помічник Dungeon Master для вилучення фактів із RPG-пригод у JSON-картки. Реалізовано тільки **Structured Extraction Service**: спільна Pydantic schema, OpenAI/Ollama adapters, bounded retry/repair pipeline та offline evaluation. RAG, UI, deployment, агенти й fine-tuning — наступні milestones.

Збережений експеримент від 01.11.2026: **240 records, 229 schema-valid, 11 failed**, усі вісім combinations мають 30 attempted, missing/skipped=0. V1 120 records використано повторно, виконано 120 v2; failures збережено. [REPORT.md](REPORT.md) містить eight-row і per-field таблиці, source-backed помилки та обґрунтований експериментальний вибір. [Mentor audit](docs/HW1_AUDIT.md) і [submission checklist](docs/SUBMISSION_CHECKLIST.md) відокремлюють завершене evidence від відкритих питань.

## Передумови

- **Python 3.12**: саме `>=3.12,<3.13` за [pyproject.toml](pyproject.toml), `.python-version` = 3.12. Курс допускає 3.11+, цей проєкт свідомо pin-ить 3.12.
- `uv`; інтернет потрібен для першого встановлення Python/packages. [Офіційні способи встановлення uv](https://docs.astral.sh/uv/getting-started/installation/).
- Для **offline review** достатньо saved texts, labels, manifests, snapshot, schema/prompts і двох saved run directories. API key, Ollama, PDF та extraction cache не потрібні.
- Для **online run** потрібні OpenAI API credentials, доступ саме до configured model, локальний Ollama із configured model та бюджет. Збережені успішні live calls підтверджують стан на 01.11.2026; сьогоднішню доступність provider/service audit не перевіряє live-запитом.
- Оригінальні 40 PDF у `data/raw/` потрібні для повторного pypdf extraction і повної перевірки source provenance. Вони ігноруються Git; права на передачу матеріалів перевіряє власник корпусу.

## Setup: Windows PowerShell

Виконуйте команди з кореня репозиторію. Якщо uv ще не встановлено й Python/pip доступні:

```powershell
python -m pip install uv
```

Після встановлення uv:

```powershell
uv python install 3.12
uv sync --locked
uv run --locked python --version
```

`uv sync --locked` встановлює locked dependencies та pytest у `.venv`, без пакування проєкту (`package=false`). `uv.lock` не оновлюйте для повторного аналізу. У цьому workspace доступний локальний launcher `.\.tools\bin\uv.exe`; його можна підставити замість `uv`. Каталоги `.tools/`, `.venv/` і caches не є частиною submission. PowerShell ExecutionPolicy змінювати не потрібно.

Audit 02.11.2026 перевірив поточне середовище через `uv sync --locked --offline --dry-run`: змін не потрібно. Це не заявляє про перевірене встановлення на чистій ОС.

### Локальні credentials

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Відредагуйте `.env` локально; ключі не додавайте в Git, чат або logs. [`.env.example`](.env.example) містить порожній `OPENAI_API_KEY` та несекретні defaults.

| Змінна | Призначення |
|---|---|
| `OPENAI_API_KEY` | Тільки ваш provider key, потрібний для OpenAI online calls |
| `PROVIDER_MODEL` | `gpt-4o-mini` у saved experiment; інший model ID без reviewed pricing profile відхиляється |
| `LOCAL_MODEL` | `qwen2.5:3b` |
| `OLLAMA_BASE_URL` | `http://localhost:11434`; adapter допускає лише loopback service |

Environment values мають пріоритет над `.env`. **Sampling A/B, context size, timeouts, retry/repair limits та output cap основного CLI беруться з [config.json](config.json)**. `LOCAL_TIMEOUT_S`, `LOCAL_TEMPERATURE`, `LOCAL_TOP_P`, `OLLAMA_CONTEXT_SIZE` та `LOCAL_MAX_OUTPUT_TOKENS` у `.env.example` налаштовують standalone local smoke; вони не перевизначають основну A/B матрицю.

### Ollama / model setup — тільки для online роботи

Встановіть [Ollama для Windows](https://ollama.com/download/windows); після цього відкрийте новий PowerShell. [Офіційний CLI reference](https://docs.ollama.com/cli).

```powershell
ollama --version
ollama list
ollama pull qwen2.5:3b
ollama show qwen2.5:3b
```

Якщо фоновий застосунок не запустив service, в окремому терміналі:

```powershell
ollama serve
```

Не запускайте другий server на зайнятому port. `pull/show` не є extraction benchmark. Digest/version/context нового service можуть відрізнятися від saved experiment; такі measurements не можна автоматично змішувати. Cloud model або інша більша модель не підставляється. [OLLAMA_ADAPTER.md](docs/OLLAMA_ADAPTER.md) містить API contract і історичні smoke reports.

## Перевірки без model calls

```powershell
uv run --locked python -m pytest -q
uv run --locked python scripts/validate_golden.py validate
uv run --locked python main.py --dry-run
```

Dry-run перевіряє frozen artifacts, review gate, settings/prompts/pricing і recorded budget; показує **240 planned initial executions**, не створює generation results і не перевіряє network readiness. Model generation calls=0. За відсутньої передумови матриця не зменшується автоматично.

Для повного source audit, якщо локально є PDF:

```powershell
uv run --locked python scripts/prepare_data.py validate --manifest data/ocr_revisions/windows-v1/manifest.jsonl
```

Цей validator перевіряє оригінальні PDF hashes, а за доступного extraction cache — відповідність source pages/slices. Відсутній PDF тут є помилкою provenance validation; він не потрібен offline evaluator-у для вже frozen inputs.

## Дійсний однокомандний online run після setup

```powershell
uv run python main.py
```

**Це реальні generation calls**, включно з платним OpenAI API. Команда створює новий unique run ID і запускає послідовно всі **30 × OpenAI/Ollama × v1/v2 × A/B = 240 initial executions**, із максимум чотирма attempts на text/configuration. На audit-кроці цю команду не запускали; збережена complete matrix реально виконана двома run selectors із reuse v1, а не новим повним bare-command benchmark.

Для вже збережених результатів використовуйте offline analysis нижче: повторні model calls заради нових timestamps не потрібні. Selectors: `--provider openai|ollama|all`, `--prompt v1|v2|all`, `--sampling A|B|all`, повторюваний `--text EXACT_TEXT_ID`, `--config`, `--run-id`. Без selectors — вся матриця.

`--resume RUN_ID` вимагає тієї самої повної identity та **тих самих selectors**. Наприклад, saved v2 run має selector `--prompt v2`. Зміна source/schema/prompt/settings/runtime/dependencies блокує reuse; terminal failed records теж зберігаються. Partial/in-flight attempts і stale lock потребують reconciliation, а не автоматичного повтору. За неверифікованих credentials/global config/quota/budget batch зупиняється.

### Очікувані outputs

| Шлях | Зміст |
|---|---|
| `results/runs/<run_id>/run.json` | Повний protocol, planned jobs, model/runtime/code/config/snapshot hashes |
| `jobs/<job_id>/attempt_*.intent.json` | Durable intent/reservation, stage, request hashes, timeout |
| `attempt_*.response.json` | Raw response/usage/error **до** validation |
| `attempt_*.validation.json` | Schema result і errors, якщо відповідь дійшла до validation |
| `result.json` + `result.sha256` | Final card/null, attempts, first/final validity, retries/repair counts, latency, usage/cost |
| `summary_*.json` | Batch outcomes, stopped flag, cumulative accounted cost |
| `results/budget.sqlite3` | Спільний cumulative homework ledger; не видаляти для «нового» ліміту |
| `results/evaluations/<unique_id>/` | Offline summary JSON/Markdown, `field_metrics.csv`, `disagreements.jsonl` |

Exit 0 означає успішні selected executions. Nonzero може означати preflight/budget blocker **або** terminal extraction failures після проходження всіх jobs: перевіряйте `record_count`, `stopped`, missing/skipped. Історичні результати не перезаписуються. Докладний [pipeline contract](docs/PIPELINE.md).

## Offline evaluation для ментора

```powershell
uv run --locked python -m src.evaluate --run results/runs/hw1_baseline_20261101_v1_ab --run results/runs/hw1_final_20261101_v2_ab
```

Команда читає 120 v1 + 120 v2 records, нічого не генерує й створює новий evaluation directory. Можна додати `--output results/evaluations/NEW_UNIQUE_NAME`; наявний output не перезаписується. `--run` потрібно повторити для кожного disjoint compatible run. Змішування несумісних protocols або overlapping repeated executions відхиляється, а не вибирається найкраща відповідь.

[Saved final evaluation](results/evaluations/hw1_final_20261101/summary.json) і [audit re-evaluation](results/evaluations/mentor_audit_20261102/summary.json) дають ті самі вісім metric rows. [64 field rows CSV](results/evaluations/hw1_final_20261101/field_metrics.csv) та [disagreements](results/evaluations/hw1_final_20261101/disagreements.jsonl) мають сталі denominators 10 golden / 30 texts, включно з failures. [Правила evaluator](docs/EVALUATION.md) описують exact matching та percentile type 7. На audit перевірено також isolated копію без `.env`, PDF, extraction cache і ledger, із заблокованими sockets; використано наявний Python environment, не чисту ОС.

## Dataset provenance і golden labels

[Inventory](data/preparation_inventory.json): 40 наданих PDF / 680 сторінок. [Active descriptor](data/active_dataset.json) указує на [manifest OCR revision](data/ocr_revisions/windows-v1/manifest.jsonl): 30 inputs, 30 document IDs, 27 adventure groups, splits **10 golden / 3 development / 17 corpus**. 12 inputs — увесь text layer PDF, 6 — завершений narrative section, 12 — інші контекстні сцени/розділи. Фрагменти не названо незалежними PDF. Pypdf читає text layer, не OCR; прийняті 20 OCR lines змінили тільки один corpus input. Повні [preparation](docs/DATA_PREPARATION.md) та [OCR reports](docs/OCR_FALLBACK.md) містять відомі дефекти й unresolved pages.

[Reviewed status](data/annotation_status.json) містить 10 labels із reviewer Roman; [frozen snapshot](data/evaluation_snapshots/hw1_2026-10-31_b69c493a71b2/snapshot.json) фіксує exact input/schema/guide/annotation hashes. `prepared_not_evaluation_frozen` у старому active pointer — історичний статус підготовки, не підстава ігнорувати наступний frozen snapshot. Source URL невідомі; author metadata/publication notices не доводять права перепоширення.

Відомий semantic review gap: п'ять golden hooks довші за guide limit 40 слів. Не змінюйте labels, guide або schema для поліпшення метрик. Після узгодженого виправлення потрібні новий snapshot і переоцінювання; за змінених input/schema/prompt/measurement policy — окремі сумісні reruns. Source facts, відсутні у finalized OCR/text, не домислюються. [Annotation guide](docs/ANNOTATION_GUIDE.md), [manual workflow](docs/MANUAL_ANNOTATION.md).

## Бюджет, secrets і точні bytes

Збережений cumulative tariff estimate на завершення експерименту **$0.1356978**, залишок homework cap **$4.8643022**. Matrix estimate **$0.1352460**; paid-provider attempts разом зі smoke — 121. Local API $0, actual provider invoice/free-quota charges і hardware/energy cost невідомі. Ціни в config — snapshot 01.11.2026, не сьогоднішня гарантія. Перед майбутніми live calls звірте доступність і тариф; automatic model substitution немає. Ledger reserves консервативну суму до виклику, unknown usage не вважає нульовою external charge; application estimates не гарантують final bill.

[`.gitignore`](.gitignore) виключає `.env`, secret-bearing environment variants, `.venv`, `.tools`, caches, `data/raw`, `data/extracted`, `data/ocr`; `.env.example`, selected texts, labels/manifests і genuine results trackable. [`.gitattributes`](.gitattributes) **вимикає line-ending conversion**, бо frozen hashes та mixed LF/CRLF мають залишатися побайтово точними. Не запускайте renormalization поверх frozen artifacts.

Пакет для публікації не включає оригінальні PDF, проміжні extraction files, справжні environment files і сторонні зміни workspace. Legacy PDF, уже наявні в Git history, залишаються без змін: ignore rules не видаляють історичні файли. Перед передачею перевірте [submission checklist](docs/SUBMISSION_CHECKLIST.md).

## Troubleshooting

| Симптом | Дія |
|---|---|
| `uv` не знайдено | Встановіть uv, відкрийте новий shell; у цьому workspace є `.\.tools\bin\uv.exe`. Не змінюйте ExecutionPolicy |
| `PermissionError` у pytest TEMP/cache | Використайте новий workspace-local basetemp за командою нижче; не змінюйте ACL/security settings |
| Missing `.env` / `OPENAI_API_KEY` | Offline evaluation ключа не потребує; для online налаштуйте локальний `.env`, не друкуйте key |
| Ollama connection refused / model missing | Запустіть service і перевірте `ollama list`, `ollama pull qwen2.5:3b`; інша модель не підставляється |
| Frozen hash / CRLF mismatch | Перевірте `.gitattributes` і точні source bytes; відновлюйте авторизовану frozen revision, не переписуйте hashes/stamps для обходу gate |
| Golden gate не проходить | Читайте конкретний path/error; current labels не auto-repair. Blank/pending templates не є golden |
| `active.lock` / partial job | Спочатку перевірте, чи процес завершився, і raw intents/ledger. Не видаляйте evidence та не повторюйте unknown paid calls автоматично |
| Context/output limit / timeout | Збережіть failure. Нові context/output/timeout settings — інший protocol; не підмішуйте його до final comparison |
| Budget exhausted / unknown history | Звірте ledger/raw attempts і external spend; не видаляйте history й не підвищуйте homework cap понад $5 |
| Re-evaluation output already exists | Задайте новий `--output` або опустіть його; історичні results лишаються незмінними |

Перевірений обхід Windows pytest TEMP/cache ACL failure:

```powershell
$mentorTestBase = Join-Path $PWD ('.tools/pytest_mentor_' + [guid]::NewGuid().ToString('N'))
uv run --locked python -m pytest -q -p no:cacheprovider --basetemp $mentorTestBase
```

Basetemp має бути новим спеціальним test directory: pytest може очищати його. Не вказуйте там project/data/results directory.

## Структура і review entry points

| Шлях | Призначення |
|---|---|
| `src/schema.py`, `src/providers.py`, `src/ollama.py` | Shared schema/contract і adapters |
| `src/pipeline.py`, `src/budget.py`, `main.py`, `config.json` | Execution, retries/repair, persistence, cumulative budget і CLI |
| `src/evaluate.py`, `tests/` | Offline scoring і synthetic/mocked regression checks |
| `prompts/v1.txt`, `prompts/v2.txt`, `prompts/repair_v1.txt` | Дві extraction versions та fixed repair; evidence у changelog |
| `data/`, `results/` | Provenance, frozen labels/inputs, historical raw measurements і derived evaluations |
| `REPORT.md`, `docs/HW1_AUDIT.md`, `docs/SUBMISSION_CHECKLIST.md` | Результати, requirement status і підготовка до передачі |

Звіти старих етапів у `docs/PROGRESS.md` зберігають історичні pending/blocked counts; для фактичного final state використовуйте REPORT, frozen snapshot, raw run headers та mentor audit.
