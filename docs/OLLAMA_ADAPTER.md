# Локальний Ollama adapter — 31.10.2026

Реалізовано [src/ollama.py](../src/ollama.py): `OllamaProvider` використовує той самий `generate(text, prompt, schema, sampling, timeout_s) -> ModelResponse`, `Sampling`, `TokenUsage` і `ProviderError`, що й зовнішній adapter. Нових залежностей не встановлювали; використано наявний `httpx` 0.28.1. Зовнішній provider не викликався.

## Конфігурація

`OllamaConfig.from_env()` завантажує `.env` без перезапису наявних environment values. Config і defaults:

| Environment name | Default |
|---|---|
| `LOCAL_MODEL` | `qwen2.5:3b`, якщо модель не вибрана |
| `OLLAMA_BASE_URL` | `http://localhost:11434` |
| `OLLAMA_CONTEXT_SIZE` | `8192` |
| `LOCAL_TIMEOUT_S` | `120` секунд |
| `LOCAL_TEMPERATURE` | `0.2` |
| `LOCAL_TOP_P` | `0.9` |
| `LOCAL_MAX_OUTPUT_TOKENS` | `2048` |

Це початкові implementation settings, не готова матриця двох sampling configurations і не виміряний production choice. `.env.example` містить усі назви; наявний `.env`, ключі й вибрані моделі не змінювалися цим кроком. Для обох adapters sampling і timeout передаються явно через спільний contract; smoke бере їх із цього config.

Запит надсилається на локальний `POST /api/chat` з `stream: false`, exported JSON Schema у `format`, незміненими `prompt` у system message та `text` у user message. `options` містить `temperature`, `top_p`, `num_ctx`, `num_predict`. Це механізми з офіційних [Chat API](https://docs.ollama.com/api/chat) і [Modelfile parameters](https://docs.ollama.com/modelfile). Source text та extraction instructions не перефразовуються окремо для локальної моделі.

Adapter приймає тільки loopback origins, вимикає environment proxies/redirect following та HTTP retries. Cloud tags і remote model metadata блокуються; інша модель не підставляється. Runtime probe читає `/api/version`, `/api/tags`, `/api/show`, `/api/ps`, не завантажує модель і не запускає generation.

## Response та помилки

Зберігаються exact `message.content`, raw response, requested/returned model IDs, done_reason, created_at, raw durations у наносекундах, wall-clock adapter duration та token counters. Total tokens обчислюються лише за наявності input і output counters; відсутні значення — `None`. Runtime report окремо зберігає доступні version/digest/quantization/model context і loaded-model metadata. Не підміняємо їх public catalog values.

Connection errors, timeout, missing model, unsupported parameter/format і server context errors піднімаються як `ProviderError` з failed-attempt `ModelResponse`. Invalid runtime JSON/message, інша returned model, `done != true`, `done_reason=length`, видимі truncation flags/warnings, досягнений output limit та reported context saturation не приймаються як успіх. Raw output/counters за наявності зберігаються й у failed response. Schema validation, transport retries, repair та benchmark persistence залишаються shared pipeline; adapter не ремонтує model JSON.

Context detection є **best effort**: без точного tokenizer чи server telemetry неможливо довести, що сервер не відкинув input мовчки. Token counts на межі context window консервативно блокуються; це не завжди доказ truncation. Відповідь з синтаксично валідним JSON не переважає observable overflow/truncation signal. Smoke також перевіряє reported loaded context після єдиного generation, якщо runtime надає це поле. Успішне передавання options у mock не є доказом, що конкретна ще не перевірена версія сервера їх застосує.

## Фактичний стан цього комп'ютера

- `ollama` не знайдено в PATH і стандартних каталогах `%LOCALAPPDATA%\Programs\Ollama` та `C:\Program Files\Ollama`.
- Процеси Ollama не знайдено. Прямі локальні probes на `/api/version` і `/api/tags` отримали connection refused, WinError 10061.
- Formal smoke prerequisite report: [results/smoke/ollama_2026-10-31_blocked.json](../results/smoke/ollama_2026-10-31_blocked.json), `kind: local_smoke_not_benchmark`, `status: blocked`, `blocker: service_unavailable`.
- **Generation calls: 0; external provider calls: 0.** Smoke model response і schema_valid — null. Це blocker report, не успішне виконання моделі й не benchmark measurement.
- Відомі host details: Windows 10 build 19045, Python 3.12.15, processor string `Intel64 Family 6 Model 154 Stepping 3, GenuineIntel`. GPU не вимірювався. Версія Ollama, присутність моделі, digest/quantization, фактичний context і GPU allocation невідомі через недоступний runtime; не стверджуємо, що модель точно відсутня, лише що це не можна перевірити зараз.

## Точні remaining setup commands

Інсталяція в цьому кроці **не виконувалася**. Офіційна [Windows download page](https://ollama.com/download/windows) наводить PowerShell install command:

```powershell
irm https://ollama.com/install.ps1 | iex
```

Альтернатива — завантажити й запустити Windows installer із тієї самої офіційної сторінки. Після встановлення відкрийте новий PowerShell, щоб він побачив оновлений PATH. [Windows documentation](https://docs.ollama.com/windows) описує background service та localhost API.

```powershell
ollama --version
# Якщо застосунок уже запустив сервер, вдруге serve не запускайте.
# Інакше — в окремому терміналі:
ollama serve
```

В іншому PowerShell:

```powershell
ollama list
# Якщо саме configured model ще немає:
ollama pull qwen2.5:3b
ollama show qwen2.5:3b
```

Це саме [вибраний 3B candidate](https://ollama.com/library/qwen2.5:3b), без заміни на більшу або cloud-модель; команди pull/serve описані в [офіційному CLI reference](https://docs.ollama.com/cli). Цей крок їх не виконував і не заявляє про завершене завантаження.

Після готовності сервісу й моделі — один smoke із новим report filename, щоб зберегти попередній blocker:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/smoke_local.py --report results/smoke/ollama_ready_smoke.json
```

Скрипт спочатку перевірить prerequisites. Лише якщо готові, він один раз передасть першу повну непорожню PDF-сторінку development input зі спільного snapshot разом із незміненим v1 prompt та exported schema. У report будуть parent hash, точні source offsets/page, excerpt hash/text, prompt/schema hashes, runtime before/after, raw response і schema validity. Це явно smoke excerpt, не підміна одного з 30 benchmark inputs. Повторних generation/repair/warm-up тут немає. При відсутній передумові або failed/truncated output команда повертає ненульовий exit status і записує фактичний blocker.

## Перевірки

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q tests/test_ollama.py
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
```

Виконано весь suite: **96 passed**, з них **25 локальних mocked checks**. Перевірено exact payload/schema, sampling/context/timeout, raw text/usage mapping, unsupported parameters/model/service, timeout, incomplete/truncated/context-saturated responses, local-only config, missing counters, runtime version/digest/remote detection та обидва smoke paths: blocked prerequisite й один generation на synthetic development-page fixture. Fixtures зберігаються лише в temporary directories, не в реальному корпусі чи golden labels.

Real smoke generation заблокована відсутністю доступного Ollama. Frozen evaluation inputs, schema, prompt v1 і reviewed labels збережено; нових model measurements немає.

## Оновлення: реальний smoke 01.11.2026

Локальний service тепер доступний: Ollama 0.40.13, qwen2.5:3b Q4_K_M, loaded context 8192. Один generation завершився `stop` і пройшов schema validation за 12.0984 s, tokens 1493 input / 331 output; зовнішніх API calls 0. [Новий звіт](../results/smoke/ollama_20261101_165939_11b4f36a.json) містить exact development-page excerpt, response та runtime metadata. Попередні blocked reports залишаються історичними. Це не benchmark; вже видно semantic error: італійський текст отримав `language=en` замість `other`. Відповідь не редагувалася. Використано standalone smoke timeout 120 s із наявної конфігурації, а не pipeline timeout 180 s.
