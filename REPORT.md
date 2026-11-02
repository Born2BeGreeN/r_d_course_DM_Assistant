# Homework 1: Adventure Assistant — звіт про Structured Extraction Service

**Стан експерименту: завершено.** Збережено всі **240 унікальних початкових виконань**: дві моделі × два extraction prompts × два sampling settings × ті самі 30 inputs. Із них **229 відповідей пройшли фінальну schema validation, 11 — failed**; missing/skipped немає. Завершеність матриці не означає правильність усіх карток. Джерела чисел: [фінальна evaluation](results/evaluations/hw1_final_20261101/summary.json), [підсумок експерименту](results/final/hw1_20261101/summary.json) і [перевірка цілісності](results/final/hw1_20261101/final_integrity.json).

Ця редакція спирається лише на збережені артефакти. Нових model calls, модельних вимірювань або виправлень даних/labels для звіту не виконувалося.

## 1. Задача і користувач

Adventure Assistant допомагає Dungeon Master готувати настільну RPG-сесію: знаходити в документах пригоди назву, рекомендований рівень, зав'язку, NPC, місця, небезпеки й нагороди та подавати їх як перевірювану JSON-картку. Цільовий користувач — майстер, який працює з довгими PDF, сценами та encounter-матеріалами й потребує швидкого огляду без вигаданих фактів. HW1 реалізує тільки Structured Extraction Service; RAG, UI, deployment, агенти й fine-tuning до цього експерименту не входять. Обсяг курсу зафіксовано в [HW1_REQUIREMENTS.md](docs/HW1_REQUIREMENTS.md).

## 2. Джерела, корпус і підготовка

За [inventory](data/preparation_inventory.json) оброблено **40 оригінальних PDF, 680 фізичних сторінок**. Це локально надані документи, а не автоматично зібрана веб-вибірка. Після тридокументного [пілоту](data/preparation_pilot.json) підготовлено решту 37 PDF та відібрано **30 непорожніх inputs із 30 різних PDF**. Межі збережено в [selection](data/selection.json) та [активному manifest](data/ocr_revisions/windows-v1/manifest.jsonl).

Приклади фактичних джерел; посилання ведуть на саме той текст, який отримували моделі:

| Оригінальний PDF | Відібраний вхід / фізичні PDF-сторінки |
|---|---|
| `1009230-TombIronKings_v2.2_SP.pdf` | [іспаномовний Tomb of the Iron King](data/texts/pdf_09543af12d2426e814f5_p005-015.txt), 5–15 |
| `1699260-Murder_in_Redwater.pdf` | [Murder in Redwater](data/texts/pdf_ed1f6f3fe3a8590a550a_p001-006.txt), 1–6 |
| `3069515-Una_Notte_da_Grifoni.pdf` | [Una Notte da Grifoni](data/texts/pdf_7a2ed7e7a7d2d48c4045_p002-008.txt), 2–8 |
| `914584-Witchlight_Beer_Festival.pdf` | [Witchlight Beer Festival](data/texts/pdf_5dcfc61ef86267e75e59_p001-007.txt), 1–7 |
| `2324173-adventures_daycare.pdf` | [Adventures Daycare](data/texts/pdf_5e5c8a49a5768666500a_p001-011.txt), 1–11 |

12 inputs містять увесь текстовий шар наданого PDF; ще 6 — завершену основну сюжетну секцію; інші 12 — opening acts, сцени чи тематичні розділи з контекстом. Фрагменти не називаються незалежними PDF або повними пригодами. Серед документів є також encounter/toolkit та видавничий excerpt. Діапазон довжин активних inputs — **6 436–31 333 символи**, разом 540 132 символи з page markers. Це символи, не model tokens. Розподіл — **10 golden / 3 development / 17 corpus**; споріднені матеріали групувалися перед split, синтетичних variants немає. Відбір curated, не випадковий; правила й прогалини описано в [DATA_PREPARATION.md](docs/DATA_PREPARATION.md).

Основний extractor — **pypdf 6.21.2**, який читає текстовий шар, **не виконує OCR**. Оригінали не змінювалися. Кандидати зберігалися окремо, зі стабільним `document_id` на основі SHA-256 PDF, hashes і маркерами `[PDF_PAGE=N]`, де N — 1-based фізична сторінка. Сегментація й окремі символьні slices зафіксовані без переказу чи домислювання тексту. Додавання іншого PDF не перенумеровує документи.

Природні дефекти: порожні обкладинки/карти, колонки зі складним порядком читання, перенос слів, розбиті ініціали, повторені заголовки, private-use glyphs і NUL усередині слова. У [diagnostics](data/preparation_diagnostics.json) є 15 сторінок із порожнім текстовим шаром, 20 OCR-review targets, 97 flags повторюваного тексту та 454 flags можливих column resets. Категорії перетинаються; це евристичні сигнали, а не 454 доведені дефекти. Нуль exceptions вилучення не доводить безпомилковість тексту.

Окремий локальний fallback використовував **Windows.Media.Ocr 10.0.19041.4355** і Windows.Data.Pdf; доступні OCR-мови `en-US`/`ru`, італійська capability була відсутня. На 19 із 20 позначених сторінок виконано recognition: 18 outputs непорожні, один порожній; непорожність не прирівнювалася до правильності. До inputs прийнято лише 20 рядків текстового блока Storm of Stonekin, PDF p.6, після OCR/source comparison асистентом; це не ручна golden-анотація користувача. Змінено один corpus input `pdf_f8d409ea73d3cc0d9ed4_p004-007`, а не golden labels; інші 29 inputs залишилися незмінними. Решта 19 сторінок — unresolved, прийнята сторінка — partial_unresolved через інші неперевірені map labels. Повні докази: [OCR_FALLBACK.md](docs/OCR_FALLBACK.md), [OCR batch](data/ocr_batch.json), [review](data/ocr_review.json), [активний pointer](data/active_dataset.json) та [OCR revision validation](data/ocr_revisions/windows-v1/validation.json). Старий pointer має історичний статус `prepared_not_evaluation_frozen`; фактичне заморожування експерименту визначає наступний snapshot.

На обох adapters використано ті самі finalized inputs із [frozen evaluation snapshot](data/evaluation_snapshots/hw1_2026-10-31_b69c493a71b2/snapshot.json). `source_url` у 30 manifest rows невідомий; 22 записи мають author, частина лише з PDF metadata. Для 11 джерел збережено publication notice Community Content Agreement, що не доводить право на перепоширення. URL завантаження та ліцензії не вигадувалися.

## 3. Golden set, схема та правила оцінювання

**Десять golden examples мають `reviewed_by: Roman`, `status: reviewed`**, annotation/input/schema hashes у [annotation_status.json](data/annotation_status.json). IDs і splits наведено в [splits.json](data/splits.json); точні десять labels, hashes та source references — у [snapshot](data/evaluation_snapshots/hw1_2026-10-31_b69c493a71b2/snapshot.json), самі картки — у [data/golden](data/golden/). Це вручну reviewed дані за зафіксованим workflow; model outputs не підмінювали golden. Review stamps і структурна валідація самі по собі не доводять семантичну узгодженість кожного label.

[Спільна JSON Schema](docs/adventure_card.schema.json) із [Pydantic v2](src/schema.py) вимагає всі вісім ключів і забороняє додаткові властивості на обох object levels:

| Ключ | Тип і зміст |
|---|---|
| `title` | string або null; явна назва пригоди |
| `language` | enum: `en`, `uk`, `mixed`, `other`, `unknown` |
| `recommended_level` | string або null; тільки прямо зазначений рівень персонажів цієї пригоди/сцени |
| `hook` | string або null; перше придатне завершене source sentence, до 40 whitespace-слів |
| `npcs` | список `{name: string, role: string|null}`; обидва ключі обов'язкові |
| `locations` | список source phrases місць і кімнат |
| `threats` | список явно підтверджених поточних небезпек із необхідними умовами |
| `rewards` | список обіцяних/отримуваних переваг або discoverable loot |

[Annotation guide](docs/ANNOTATION_GUIDE.md) вимагає оригінальних імен, spelling і мови джерела, коротких буквальних фраз, null/[] за відсутності інформації та локального evidence для aliases. Named animals/offstage actors можуть бути NPC; автори, анонімні групи й reference-only cameos — ні. NPC/spell levels, CR, вік або рівень іншої атракції не визначають party level. Невидимий моделям текст PDF-зображення не використовується для доповнення label. Provenance, execution metadata й evidence notes перебувають поза карткою.

[Evaluator](src/evaluate.py) працює офлайн. Зафіксовані правила `hw1-exact-fields-v1`: строки — лише whitespace collapse і casefold; punctuation/діакритика значущі; списки — рівність повних множин незалежно від порядку; NPC — множини normalized name/role pairs; enum і null — exact. Часткового кредиту немає. Failed extraction має **всі 8 полів incorrect**, зокрема за порожнього golden. Missing/skipped не вилучаються зі знаменника.

Field accuracy має denominator 10; mean — correct/80. Populated accuracy виключає лише null, [] та порожній рядок golden, тому denominator тут **62**. First-pass/final validity обчислено на всіх 30 texts; first-pass означає initial logical generation після можливого transport retry, до schema repair. Latency включає retries, waits і repairs; p50/p95 — **linear interpolation `h=(n−1)p`, Hyndman–Fan type 7**. Порожня вибірка failures не має percentile; unknown durations не замінюються нулем. Деталі: [EVALUATION.md](docs/EVALUATION.md).

## 4. Моделі, prompts, runtime та виконання

| Компонент | Зафіксована конфігурація / evidence |
|---|---|
| Provider | requested `gpt-4o-mini`; усі збережені returned model IDs — `gpt-4o-mini-2024-07-18`; OpenAI Responses API, strict JSON Schema, SDK retries=0 |
| Local | `qwen2.5:3b`, returned `qwen2.5:3b`; Ollama **0.40.13**, **3.1B Q4_K_M**, digest `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`; configured/loaded context **8192**, native model metadata **32768** |
| Середовище | Windows 10 build 19045; Python **3.12.15**, Pydantic **2.14.1**, OpenAI SDK **3.42.0**, httpx **0.28.1**, SDK httpx2 **2.16.0** |
| Hardware inventory перед v2 | Intel Core i7-12700H, 14 cores / 20 threads; RAM 16 782 049 280 bytes (~15.63 GiB); NVIDIA RTX 3050 Ti Laptop GPU та Intel Iris Xe. Inventory не є виміром GPU utilization чи energy |
| Sampling A / B | A: temperature **0.2**, top_p **0.9**; B: temperature **0.8**, top_p **0.9** |
| Limits | provider/local timeout **60/180 s**, logical-request deadline **150/390 s**; output cap **2048 tokens**, Retry-After bound **30 s**, default retry delay **1 s** |
| Retry/repair | максимум один transport retry на generation або repair; максимум один schema-repair request; максимум **4 actual attempts** на document/configuration; приховані SDK/HTTP retries вимкнені |

Джерела таблиці: [config.json](config.json), [experiment metadata](results/final/hw1_20261101/experiment_metadata.json), [hardware inventory](results/final/hw1_20261101/hardware_verified.json) та [returned IDs audit](results/final/hw1_20261101/final_integrity.json). Наявність GPU не доводить однакове його завантаження чи що кожен запит виконувався саме на ньому. Фоновий load, енергія та грошова ціна hardware/runtime не вимірювалися.

[V1](prompts/v1.txt) — source-only baseline, 449 слів. [V2](prompts/v2.txt) — 668 слів: локальна перевірка evidence, scope рівня, повне source sentence для hook, coverage named actors/rooms, deduplication і qualifiers. За [changelog](prompts/CHANGELOG.md), v2 створено лише на трьох designated development texts і їхніх v1 results, без golden answers. [Repair v1](prompts/repair_v1.txt) незмінно спільний для обох extraction versions і не рахується другою extraction version.

До validation зберігалися raw response та usage; repair мав би отримати source, invalid answer і validation errors із тією самою schema. Фактично в матриці **repairs=0**. Новий v2 run використав ту саму generation code/runtime/settings protocol, що й checkpoint: **120 matching v1 records reused, 120 missing v2 виконано**. Мітки часу не оновлювалися повторними calls, failures не перезапускалися заради кращих показників. Повні headers: [v1 run](results/runs/hw1_baseline_20261101_v1_ab/run.json), [v2 run](results/runs/hw1_final_20261101_v2_ab/run.json).

Перед фінальною evaluation виправлено тільки offline compatibility check для CRLF: hash сирого v2-файлу відрізняється від hash effective text після `Path.read_text` universal newline decoding. Надалі незалежно перевіряються і незмінні file bytes, і фактично submitted text. Generation code, prompts, labels і measurements не змінено; AST scoring functions незмінний. Старий checker і old/new hashes збережено в [audit виправлення](results/final/hw1_20261101/evaluator_compatibility_fix.json). Збережений [final integrity audit](results/final/hw1_20261101/final_integrity.json) фіксує **127 passed tests**; на цьому редакційному кроці їх повторно не запускали.

## 5. Вісім рядків результатів

У кожному рядку attempted=30, missing=0, skipped=0. `S/F` — schema-valid successes / failed terminal records; це не ручна оцінка фактичної правильності.

| Модель | Prompt / sampling | Attempted; S/F; missing/skipped | Mean field, % | Populated, % | First/final valid, % | p50 / p95, s | API estimate, USD | USD / 1000 attempted |
|---|---|---|---:|---:|---|---|---:|---:|
| gpt-4o-mini | v1 / A | 30; 30/0; 0/0 | 28.75 | 29.03 | 100/100 | 3.0155 / 5.3362 | 0.0333426 | 1.1114 |
| gpt-4o-mini | v1 / B | 30; 30/0; 0/0 | 28.75 | 29.03 | 100/100 | 2.8675 / 5.5623 | 0.0329436 | 1.0981 |
| gpt-4o-mini | v2 / A | 30; 30/0; 0/0 | 28.75 | 29.03 | 100/100 | 3.1090 / 5.3884 | 0.0349692 | 1.1656 |
| gpt-4o-mini | v2 / B | 30; 30/0; 0/0 | 30.00 | 30.65 | 100/100 | 3.0545 / 6.7486 | 0.0339906 | 1.1330 |
| qwen2.5:3b | v1 / A | 30; 27/3; 0/0 | 18.75 | 24.19 | 90/90 | 41.0545 / 165.5284 | 0 | 0 |
| qwen2.5:3b | v1 / B | 30; 28/2; 0/0 | 20.00 | 25.81 | 93.33/93.33 | 30.9295 / 79.5702 | 0 | 0 |
| qwen2.5:3b | v2 / A | 30; 27/3; 0/0 | 21.25 | 25.81 | 90/90 | 11.7035 / 51.8377 | 0 | 0 |
| qwen2.5:3b | v2 / B | 30; 27/3; 0/0 | 21.25 | 27.42 | 90/90 | 13.6170 / 68.9096 | 0 | 0 |

Точні unrounded values та denominators: [summary.json](results/evaluations/hw1_final_20261101/summary.json). Повний перелік source/result references і hashes: [240 records](results/final/hw1_20261101/matrix_records.jsonl).

### Точність кожного поля

[Машиночитана per-field таблиця — 64 рядки CSV](results/evaluations/hw1_final_20261101/field_metrics.csv). Нижче кожен відсоток означає correct/10, а не token/entity F1.

| Модель / prompt / sampling | title | language | recommended_level | hook | npcs | locations | threats | rewards |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| gpt-4o-mini / v1 / A | 60% | 100% | 20% | 0% | 0% | 10% | 10% | 30% |
| gpt-4o-mini / v1 / B | 60% | 100% | 20% | 0% | 0% | 10% | 10% | 30% |
| gpt-4o-mini / v2 / A | 60% | 100% | 20% | 0% | 0% | 10% | 10% | 30% |
| gpt-4o-mini / v2 / B | 60% | 100% | 30% | 0% | 0% | 10% | 10% | 30% |
| qwen2.5:3b / v1 / A | 60% | 90% | 0% | 0% | 0% | 0% | 0% | 0% |
| qwen2.5:3b / v1 / B | 50% | 80% | 20% | 0% | 0% | 0% | 0% | 10% |
| qwen2.5:3b / v2 / A | 60% | 90% | 10% | 0% | 0% | 0% | 0% | 10% |
| qwen2.5:3b / v2 / B | 60% | 90% | 10% | 0% | 0% | 0% | 0% | 10% |

Нуль для `npcs` означає відсутність повністю однакової множини name/role pairs, а не відсутність будь-яких правильно знайдених NPC. Аналогічно `hook=0%` — exact-match результат; це не доведення, що кожна відповідь позбавлена сюжетного змісту.

### Failures і latency

Усі **11 failures локальні**: 6 `context_window_saturated`, 1 `local_timeout`, 4 `output_truncated_or_limit_reached`. Їхні [result references](results/final/hw1_20261101/summary.json) та raw attempts збережено. У provider rows failures=0, тому failure-only percentiles не обчислюються.

| Local prompt / sampling | Success n; p50/p95, s | Failed n; p50/p95, s |
|---|---|---|
| v1 / A | 27; 39.8120 / 59.4612 | 3; 246.4370 / 351.4283 |
| v1 / B | 28; 30.0545 / 80.8046 | 2; 54.3120 / 61.6668 |
| v2 / A | 27; 10.8120 / 20.3353 | 3; 53.3290 / 86.7829 |
| v2 / B | 27; 13.1880 / 34.1485 | 3; 76.8130 / 81.5092 |

V2 змінив mean field match OpenAI A/B на +0/+1.25 процентного пункту, local A/B на +2.50/+1.25. Local B validity погіршилася на 3.33 pp. Зниження observed local p50 не є доведеним причинним ефектом prompt: порядок запусків і background hardware load не контролювалися. Provider v2 B має трохи більші latency/cost, ніж v1 B.

## 6. Calls, вартість і бюджет

Матриця: **240 initial executions + 3 transport retries = 243 actual call attempts**, schema repair requests=0. Із цих attempts 120 provider і 123 local. Окремо за історію homework є **4 auxiliary calls**: provider smoke 1, local smoke 1, local warm-ups 2; blocked smoke report має calls=0 і не є вимірюванням моделі. Разом — 247 actual attempts, з них **121 paid-provider attempt у ledger**; слово paid тут означає зовнішню тарифіковану категорію, а не підтверджений invoice debit. Розділення зафіксовано в [final integrity](results/final/hw1_20261101/final_integrity.json) і [auxiliary records](results/final/hw1_20261101/summary.json).

Збережений [pricing preflight](results/final/hw1_20261101/preflight.json) фіксує перевірку 01.11.2026: standard text rates GPT-4o Mini за 1M tokens — input **$0.15**, cached input **$0.075**, output **$0.60**. Це не Batch discount. Cached input є частиною input; reasoning/thinking не додається повторно поверх output; окремого thinking/cache-write тарифу для обраної моделі не заявлено. Профіль також зберігає історичну позначку deprecated; у реальних runs використано configured model без заміни. У цьому звіті ціни повторно онлайн не перевірялися.

Matrix tariff-equivalent estimate: **$0.1352460**. Сукупний homework ledger разом із provider smoke: **$0.1356978**; залишок USD 5 ліміту — **$4.8643022**. Відомий provider usage є для всіх external attempts, unknown external usage attempts=0, unsettled paid reservations=0. **Фактичні invoice/free-quota charges невідомі:** usage×tariff не доводить списання або безкоштовність. Application estimates/reservations не гарантують фінальний рахунок провайдера. Local API cost **$0**; hardware, energy та грошова вартість runtime **невідомі**, не нульові за припущенням.

Cost/1000 = сума external attempt estimates, включно з retries/repairs, поділена на attempted texts і помножена на 1000. За невідомого external usage total/per-1000 мали б лишатися unknown із separate subtotal/reservation; такі charges не підміняються нулем.

## 7. Чотири характерні, підтверджені джерелом помилки

Нижче наведено **чотири фактичні помилки щодо джерела й чинних правил**, а не лише довільні exact-match відмінності. Перші дві також мають manually reviewed golden expectations; для двох development cases expected виведено зі збереженого source і annotation rule, **це не нові golden annotations** і не додаткові вимірювання accuracy. Повні автоматичні розбіжності — у [disagreements.jsonl](results/evaluations/hw1_final_20261101/disagreements.jsonl).

1. **Неправильна мова.** Input `pdf_09543af12d2426e814f5_p005-015`, qwen2.5:3b/v2/A. Expected: `language="other"` у [golden](data/golden/pdf_09543af12d2426e814f5_p005-015.json); observed: `"en"` у [result](results/runs/hw1_final_20261101_v2_ab/jobs/610da290368aea215a9ef38c250d9c9520c83c0501b795ecdbca49bda61cd05c/result.json). **Source evidence:** [PDF p.5](data/texts/pdf_09543af12d2426e814f5_p005-015.txt) містить іспанську оповідь, зокрема «es una miniaventura introductoria para tres a cinco personajes»; англійська назва не змінює мову оповіді. **Гіпотеза, не доведена причина:** модель могла надмірно орієнтуватися на англійські назви/терміни.

2. **Пропущений сюжетно релевантний named actor.** Input `pdf_ed1f6f3fe3a8590a550a_p001-006`, gpt-4o-mini/v2/A. Expected: NPC `{"name":"Marcus Redwood","role":"merchant"}` у [golden](data/golden/pdf_ed1f6f3fe3a8590a550a_p001-006.json); observed: Marcus відсутній у [списку result](results/runs/hw1_final_20261101_v2_ab/jobs/5a5bad1af7ec618555a25d423b0e84600e354814909efe8c861ebc2b467d5d42/result.json). **Source evidence:** [PDF p.2, Summary](data/texts/pdf_ed1f6f3fe3a8590a550a_p001-006.txt) прямо називає «the wealthy merchant Marcus Redwood» і його смерть причиною розслідування. Offstage victim лишається центральною названою особою поточного сюжету. **Гіпотеза:** coverage могла обмежитися headings зі списками NPC; механізм уваги не вимірювався.

3. **Вигаданий party level замість явної рекомендації.** Development input `pdf_5e5c8a49a5768666500a_p001-011`, qwen2.5:3b/v1/A. Expected за source: `recommended_level="3rd-level"`; observed: `"party-level 1"` у [result](results/runs/hw1_baseline_20261101_v1_ab/jobs/200158f84134d52e9944cb073f0cada918319af059aa57f294c2a42f7a3e9736/result.json). **Source evidence:** [PDF p.4, PLAY AS A KID](data/texts/pdf_5e5c8a49a5768666500a_p001-011.txt): «Each player should create a regular 3rd-level character of any race and class.» **Гіпотеза:** змішування чисел із віком/stat blocks або default inference; причинний механізм не встановлено.

4. **Рівень згаданої атракції перенесено на пригоду.** Development input `pdf_5dcfc61ef86267e75e59_p001-007`, gpt-4o-mini/v1/A. Expected за scope rule: `recommended_level=null`; observed: `"1st level characters"` у [result](results/runs/hw1_baseline_20261101_v1_ab/jobs/ff26c9f549490d3adbb84b8aeb8774f0d0e29ab1982e25b886fb4bcc1229810b/result.json). **Source evidence:** [PDF p.1](data/texts/pdf_5dcfc61ef86267e75e59_p001-007.txt) прив'язує фразу «designed for 1st level characters» до Mystery Mine, тоді як [annotation guide](docs/ANNOTATION_GUIDE.md) прямо забороняє переносити цей level без явного зв'язку на весь фестиваль. **Спостережуване порушення:** втрачено scope рекомендації. **Гіпотеза:** близькість числової фрази до вступу сприйнято як загальну вимогу; це не доказ внутрішнього reasoning моделі.

Розбіжність на кшталт `"1-2"` проти `"level 1 - 2"` оцінюється як incorrect за frozen matching rule, але сама по собі не є доведеною фактичною помилкою; її не використано для штучного збільшення кількості прикладів.

## 8. Вибір конфігурації

Для наступного пілоту з людською перевіркою обираю **gpt-4o-mini / v2 / B (temperature=0.8, top_p=0.9)**: це найбільший mean field exact-match **30.00%**, populated accuracy **30.65%**, schema validity **100%**, p50/p95 **3.0545/6.7486 s**, тарифна оцінка **$1.1330 на 1000 attempted texts**. Порівняно з v1/B приріст лише **1.25 pp — один додатковий correct field із 80**, із трохи більшими latency та cost; local v2 має 21.25% mean і 90% validity, а нульовий local API тариф не враховує hardware/runtime. **Вибір на тих самих десяти golden examples є навчальним course experiment, не доказом загальної production performance чи статистичної переваги**; golden тут також використано для selection, тож незалежного фінального test set немає. Переглянути вибір слід після узгодження annotation policy та нової frozen revision, перевірки на більшій незалежній вибірці, зміни вимог до приватності/offline роботи, доступності/ціни моделі або runtime limits. Поточні labels, prompts і результати заднім числом не змінюються.

## 9. Обмеження та твердження для вашої фактичної перевірки

- **Мала й невипадкова вибірка.** Лише 10 golden і по одному результату на text/configuration; відсутні повторні runs, confidence intervals та незалежний test set. За збереженим preparation review переважає англійська: 28 inputs, один іспанський і один італійський. Репрезентативне mixed-language/українське покриття не підтверджене; missing-field coverage системно не виміряно.
- **Exact matching і annotation consistency.** Повні множини та буквальні фрази штрафують частково правильні відповіді. У незмінених reviewed labels `hook` має понад 40 whitespace-слів у п'яти IDs: `pdf_f72f9d30936a1f7366c8_p001-004` — 72, `pdf_fb44e1ed23f8853082fc_p001-005` — 59, `pdf_c6ba72f7dd1477ae00a7_p001-008` — 54, `pdf_6f9d4eb751a6671c2284_p001-006` — 82, `pdf_09543af12d2426e814f5_p005-015` — 44. Це перевірено підрахунком у saved JSON і суперечить чинному правилу ≤40; labels/метрики **не виправлялися**. Потрібен ваш review policy, а не автоматичний висновок, що всі hook outputs погані.
- **OCR і source fidelity.** Більшість flagged pages лишилася unresolved; не всі відсутні на text layer факти доступні моделі. Не виконано повного visual audit 680 сторінок. Pypdf reading-order flags можуть бути false positives. Не можна додавати невидимі source facts або приписувати будь-який mismatch саме OCR без доказу.
- **Failures і context/output limits.** Усі 11 failures включено; validity не доводить повне прочитання source. Silent server-side truncation загалом не виключено. Зміна context/output/timeout створила б інший protocol і потребує окремого порівняння.
- **Гроші й hardware.** Usage-based estimates відомі, actual invoice/free-quota charges, енергія та hardware amortization — ні. Hardware inventory знято перед v2, utilization/background load не виміряні; latency не слід переносити на інший комп'ютер чи видавати за чистий причинний ефект prompt.

**Що потребує вашого factual review:** (1) походження PDF, author metadata, фактичні download URLs, право передати матеріали ментору та якість 20 прийнятих OCR-рядків; (2) відповідність десяти review stamps вашій ручній перевірці та узгодження п'яти довгих golden hooks із guide, а також title/role policy; (3) чи репрезентують 30 curated inputs і ділянки PDF ваші реальні DM-сценарії; (4) provider invoice/free-quota списання — цього немає в saved usage; (5) чи є достатньою якість і human-review workflow для вашого застосування. Жоден із цих пунктів у звіті не подано як уже підтверджений вами факт.

## 10. Відтворюваність та посилання

Повторний аналіз лише збережених measurements, із новим output directory за замовчуванням:

```powershell
uv run python -m src.evaluate --run results/runs/hw1_baseline_20261101_v1_ab --run results/runs/hw1_final_20261101_v2_ab
```

Основні артефакти: [eight-row JSON](results/evaluations/hw1_final_20261101/summary.json), [field_metrics.csv](results/evaluations/hw1_final_20261101/field_metrics.csv), [disagreements](results/evaluations/hw1_final_20261101/disagreements.jsonl), [experiment/hardware metadata](results/final/hw1_20261101/experiment_metadata.json), [matrix records із hashes](results/final/hw1_20261101/matrix_records.jsonl), [baseline checkpoint](docs/HW1_BASELINE_CHECKPOINT.md), [progress](docs/PROGRESS.md).

Історичний `report_sha256` у final_integrity.json належить редакції REPORT на момент завершення експерименту, а не цій пізнішій редакційній версії. Аудит і raw results не переписувалися, щоб узгодити їх із новим текстом звіту.
