# Provider adapter і baseline prompt — 31.10.2026

Поточний вибір після прямого запиту користувача — **`gpt-4o-mini`**. Оновлено тільки model entry у локальному `.env`, решту його байтів збережено. Модель є у [публічному каталозі OpenAI](https://developers.openai.com/api/docs/models/gpt-4o-mini) зі structured outputs/Responses; [Responses reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create) документує temperature/top_p. Нижче описано попередню несумісність Sol як історичне рішення, не поточний blocker. Доступ вашого акаунта не перевірявся API-запитом.

Для `gpt-4o-mini` adapter не передає reasoning-параметр. Через справжній SDK та synthetic MockTransport перевірено model ID, strict schema, temperature 0.2/0.8, top_p 0.9 та відсутність reasoning. Provider suite: **16 passed**. Ці значення — offline-перевірки сумісності payload, не збережені результати експерименту. Live calls не було.

У локальній конфігурації вже є OpenAI credentials та `PROVIDER_MODEL`, тому реалізовано OpenAI adapter, як вимагає пріоритет наявного course provider. `.env` не змінено, credentials не виводилися. Gemini-кандидата не використано як мовчазну заміну. Для цього адаптера потрібні лише **`OPENAI_API_KEY`** і **`PROVIDER_MODEL`**; `.env.example` містить порожні значення, а environment має пріоритет над `.env`.

## Перевірений інтерфейс

Фактично встановлено й проінспектовано `openai` **3.42.0**. `pyproject.toml` та `uv.lock` оновлено; попередні залежності збережено. Перевірено signatures `OpenAI`, `with_options`, `responses.create` і response/usage types. Поточний SDK використовує `httpx2`; HTTP-mocks використовують саме його MockTransport, без мережі.

Спільний contract у `src/providers.py`:

```python
generate(text, prompt, schema, sampling, timeout_s) -> ModelResponse
```

`Provider` — Protocol для майбутнього локального адаптера. `Sampling` явно містить temperature/top_p та configurable max_output_tokens (початковий технічний ліміт 2048, не результат експерименту). `OpenAIProvider.from_env()` завантажує credentials, не виконує discovery або inference. Вибір моделі обов'язковий; ID передається без перейменування чи fallback.

Structured output: `client.with_options(max_retries=0, timeout=timeout_s).responses.create(...)`, де `text.format` містить `type: json_schema`, `name: adventure_card`, `strict: true` та незмінну shared schema. Це реальний structured-output API mechanism, описаний в [офіційній документації](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses), не тільки прохання повернути JSON. `prompt` передається окремим `instructions`, весь вихідний документ — окремим user input без переформатування. Tools порожні, streaming та server-side storage вимкнено.

Timeout SDK задається в секундах. SDK retries примусово дорівнюють нулю, включно з injected client; це перевірено 429/503/timeout HTTP-mocks. Один generate — максимум один SDK call, без validation/repair/retry/persistence. Попередній аргумент Sampling/timeout validation стосується конфігурації, а не model-generated card.

`ModelResponse` зберігає точний output text без strip/JSON parse, raw SDK response dictionary, requested/returned model IDs, response/request IDs, finish status, input/output/total/cached/reasoning usage та raw usage, UTC start і adapter duration. Usage, якого немає, залишається `None`, а не вигаданим нулем. Refusal, incomplete_details і provider error залишаються доступними для pipeline. Invalid/truncated JSON не ремонтується.

Transport/API errors піднімаються як `ProviderError` з failed `ModelResponse`: SDK exception type, HTTP status/request ID за наявності, timing, точний requested model і SDK call count. SDK error body/message і credentials не додаються до exception/logs. Потенційна вартість невдалого запиту невідома, її не можна автоматично вважати нульовою. Загальне benchmark timing, accounting, bounded retries, schema validation, repair і persistence залишаються майбутньому shared pipeline.

## Наявна model configuration несумісна із sampling

У `.env` задано `GPT-6.1-Sol`. Публічна [сторінка OpenAI](https://developers.openai.com/api/docs/models/gpt-6.1-sol) документує API model ID `gpt-6.1-sol` та structured outputs. Це підтвердження публічного каталогу, не перевірка доступу вашого акаунта; endpoint models/list/get не викликався.

[Офіційний compatibility guide](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6.1-sol) вказує: GPT-6.1 Sol не підтримує reasoning effort `none`, а temperature/top_p не підтримуються з іншими reasoning settings. Отже, навіть виправлення регістру ID не дозволить виконати потрібний sampling experiment на цій моделі. Adapter повертає `unsupported_model_sampling` до SDK call для цієї family. Немає автоматичного переходу на іншу модель, видалення sampling controls або платного probe.

Перед live-кроком потрібен явно обраний sampling-compatible model ID у `PROVIDER_MODEL` та перевірка його актуальної доступності/доступу. Для GPT-5/GPT-6 requests adapter явно задає reasoning `none`; для інших IDs не додає цей параметр. Невідомі/непідтримувані моделі чи API parameters не замінюються: provider errors передаються pipeline. Загальна наявність параметрів у SDK не є доказом підтримки довільною моделлю.

На початку також перевірено Gemini SDK 2.33.0 (`response_json_schema`, JSON MIME type, temperature/top_p, HttpRetryOptions) та [Gemini-каталог](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite). Цей шлях не є поточним course provider і не був активований.

## Baseline й фактичні перевірки

`prompts/v1.txt` вимагає тільки source facts, original names/language, required keys, null/[] за відсутності даних; document instructions трактуються як untrusted data. Правила відповідають shared schema/annotation guide, не містять golden answers. `prompts/CHANGELOG.md` фіксує initial v1 без тверджень про виміряну якість; v2 ще не реалізовано.

Виконано:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q tests/test_providers.py
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
```

Provider tests проходять через справжній SDK із синтетичним HTTP MockTransport: wire-format JSON Schema, sampling, timeout, exact input/text, requested/returned IDs, usage including zero/None, incomplete/refusal, 400/404/429/503 errors, timeout, вимкнені retries, environment config і preflight rejection несумісної Sol family. Живих зовнішніх model calls не було. Синтетичні outputs не збережено як experiment results.

Frozen evaluation snapshot не переписувався: inputs, schema/guide та 10 human-reviewed labels залишилися незмінними. Оскільки додано SDK, поточний uv.lock відрізняється від recorded runtime hash початкового snapshot. Майбутня execution identity має посилатися на frozen input/schema/annotation hashes і додатково записати нові SDK/dependency lock та prompt hashes; не стверджувати повний збіг старого runtime. Це не вимірювання моделі й не завершений benchmark.
