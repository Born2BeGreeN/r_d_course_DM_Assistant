# Ручна анотація десяти golden-входів

Підготовлено лише workflow і порожні шаблони. Відповіді маєте самостійно заповнити й перевірити ви; model-generated картка не є вручну розміченим golden data.

1. Прочитайте [ANNOTATION_GUIDE.md](ANNOTATION_GUIDE.md) і перегляньте [JSON Schema](adventure_card.schema.json). Відкрийте [індекс десяти текстів](../data/golden_templates/INDEX.md): кожен ID має посилання на finalized UTF-8 input, шаблон, оригінальний PDF і точні фізичні 1-based PDF-сторінки.
2. Прочитайте весь зв'язаний input. PDF використовуйте для provenance/діагностики, але не додавайте фактів, яких немає у тексті, що отримають моделі. Golden-входи з базового manifest перевіряються проти active snapshot; при іншій ревізії gate закриється замість непомітної підміни джерела.
3. Скопіюйте відповідний `data/golden_templates/<text_id>.json` до **`data/golden/<text_id>.json`**, якщо такого файла ще немає. Існуючі labels не перезаписуйте копіюванням шаблону. Усі answers пишіть у копії; templates залишайте порожніми.
4. Заповніть усі вісім ключів за джерелом. `language: null` у шаблоні — навмисний unfinished marker, а не відповідь: ви маєте вибрати enum самостійно. Інші `null`/`[]` також не є готовими анотаціями — перевірте кожне поле. Не додавайте placeholder NPC; кожен справжній NPC потребує `name` і `role`, де роль може бути `null`.
5. Звірте завершену картку з input, назвами, alias, порядком/дедуплікацією та правилами missing facts. Для unresolved питань залишайте entry pending і ведіть notes поза карткою. Порожні рядки та повністю порожня картка не проходять completion gate; не вигадуйте фактів для обходу перевірки — спочатку з'ясуйте якість джерела.
6. Лише після власного ручного review позначте відповідний entry у `data/annotation_status.json` як reviewed, вкажіть себе й hash завершеного JSON, як описано нижче.

## Як зафіксувати review

`data/annotation_status.json` — окремий metadata-файл; ці поля не належать AdventureCard. Для кожного із десяти entries спочатку встановлено:

```json
{
  "status": "pending",
  "reviewed_by": null,
  "annotation_sha256": null
}
```

Після ручного завершення одного JSON отримайте SHA-256 його точних байтів. Ця команда **тільки друкує hash**, не змінює status і не позначає review:

```powershell
$textId = 'COPY_EXACT_ID_FROM_INDEX'
.\.venv\Scripts\python.exe -X utf8 scripts/validate_golden.py hash "data/golden/$textId.json"
```

У відповідному entry вручну змініть `status` на `"reviewed"`, `reviewed_by` — на ваше ім'я/ідентифікатор, `annotation_sha256` — на надруковані 64 hex-символи. Не змінюйте `text_id`, `input_text_sha256`, `annotation_path` та hashes schema/guide, щоб приховати несумісність. Вони прив'язують review до правильного джерела й правил. Реальні ключі API для цього не потрібні.

Якщо після review редагуєте JSON, поверніть entry у pending; після повторної ручної перевірки знову обчисліть hash і лише тоді поставте reviewed. Зміна навіть whitespace змінює hash. Для великої зміни джерела/схеми/правил потрібне окреме узгодження ревізій, а не автоматичне «виправлення» labels.

## Completion gate

```powershell
# Read-only перевірка, без LLM, автоанотації або семантичного repair
.\.venv\Scripts\python.exe -X utf8 scripts/validate_golden.py validate
```

Exit code **0** означає, що всі десять selected IDs мають schema-valid, непорожні картки в `data/golden/`, правильні input hashes і явні reviewed stamps, прив'язані до байтів JSON. Pending/неповні записи дають exit code **1**. Проміжний стан з одним completed і дев'ятьма pending теж навмисно не проходить загальний gate.

Validator відхиляє пропущені/зайві keys, malformed NPC, невалідний enum, duplicate JSON keys, змінені input/annotation hashes, невибрані labels і перетин development/golden. Він не змінює labels або status. Не спрямовуйте `annotation_path` на templates: gate приймає тільки точний `data/golden/<text_id>.json`.

Прапорець reviewed — ваша явна декларація ручної роботи. Validator перевіряє структуру, зв'язок із реальним input, стан та hashes, але не може довести авторство набору тексту або семантичну правильність відповіді. Жоден автоматично отриманий JSON не позначається human-reviewed асистентом.

Поточний початковий стан: **0/10 completed, 10 pending**, completed JSON ще немає. Історичний результат початкового запуску збережено в [golden_validation_pending.json](../data/golden_validation_pending.json); актуальний стан завжди перевіряйте повторною командою.

Повторна команда підготовки `.\.venv\Scripts\python.exe scripts/validate_golden.py prepare` не перезаписує існуючі labels/status. Вона створює лише відсутню початкову pending-status структуру й однакові blank artifacts; відмінний існуючий шаблон/індекс не замінюється мовчки. Експерименти цим workflow не запускаються.
