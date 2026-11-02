# Локальний OCR fallback — 26.10.2026

Продовження [звіту PDF-підготовки](DATA_PREPARATION.md). OCR реально виконано локально; LLM і зовнішні model API не використовувалися. Python-залежності та системні security settings не змінювалися.

## Інструмент і межі

Доступні в поточному Windows середовищі `Windows.Media.Ocr` і `Windows.Data.Pdf` викликаються з Python через звичайні Windows PowerShell commands. PDF renderer створює зображення при цільових 300 DPI, з обмеженням розміру OCR engine; потім OCR читає bitmap. Повідомлення про це API див. у [Microsoft RecognizeAsync](https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr.ocrengine.recognizeasync?view=winrt-26100) та [Microsoft RenderToStreamAsync](https://learn.microsoft.com/en-us/uwp/api/windows.data.pdf.pdfpage.rendertostreamasync?view=winrt-28000).

Фактично перевірене середовище записано в [ocr_environment.json](../data/ocr_environment.json):

- OCR DLL: `10.0.19041.4355 (WinBuild.160101.0800)`.
- PDF renderer DLL: `10.0.19041.320 (WinBuild.160101.0800)`.
- OS version, яку повернув runtime: `10.0.19045.0`.
- AvailableRecognizerLanguages: `en-US`, `ru`. Італійський `it-IT` відсутній.

Це Windows-specific fallback, перевірений у цьому середовищі. OCR не має гарантованої точності; confidence від цього adapter не отримується й зберігається як `null`. Таймаут WinRT-операції — 45 секунд, усього subprocess — 120 секунд; автоматичних повторних OCR-запитів немає. Кеш використовується лише для того самого PDF hash, language та rotation. Для іншого запуску/інструмента використовується новий output directory.

## Реальний пілот і решта сторінок

Спочатку виконано Goblin Giftsmas, PDF p.3. Результат `giy` збережено в `data/ocr/windows-v1/`; [ocr_pilot.json](../data/ocr_pilot.json) фіксує цей запуск. Перегляд PNG показав повернуту рукописну карту. Повтор із явним clockwise rotation 270° повернув `illfqye`; обидва результати непридатні й не включені до корпусу. Поворот записано в [ocr_rotations.json](../data/ocr_rotations.json), повтор — у [ocr_pilot_rotated.json](../data/ocr_pilot_rotated.json).

Додатковий пілот на друкованій обкладинці Night of Masks and Monsters, PDF p.1, прочитав:

```text
A NIGHT OF
MASKS AND MONSTERS
BY ASHLEY WARREN
```

Водночас він пропустив частину підзаголовка: реальний OCR-рядок — `IN THE STRANGE OF MAGIC LURKS EVERYWHERE.`. Він **не доповнювався** за змістом. [ocr_pilot_printed.json](../data/ocr_pilot_printed.json) зберігає походження. Частково успішний printed-text пілот дав підставу обробити решту позначених сторінок, але не автоматично прийняти результати.

[ocr_batch.json](../data/ocr_batch.json) охоплює рівно 20 раніше позначених сторінок; інші 660 сторінок не відправлялися до OCR. Два пілотні результати повторно використано з кешу. На 19 із цих 20 сторінок виконано recognition: 18 дали непорожній текст, одна — порожній. Італійська обкладинка не розпізнавалася через відсутню мову. Початковий невдалий Goblin-пілот — додаткова спроба поза цими 19. Непорожній OCR не прирівнюється до успішного відновлення.

Окремо збережено PNG, сирий UTF-8 OCR-текст і JSON із PDF hash, 1-based page, tool/version, мовою, rotation, rendering dimensions/DPI та hashes тексту й PNG. Каталог `data/ocr/` локальний та ігнорується Git. Версії, hashes, рішення та прийняті рядки залишаються trackable у [ocr_review.json](../data/ocr_review.json).

## Прийняте відновлення та unresolved

На Storm of Stonekin, **фізична PDF p.6**, відновлено текстовий блок Trademoot Features. Його перші 20 OCR-рядків звірено із зображенням і прийнято без перефразування. Буквальний початок:

```text
TRADEMOOT FEATURES
Old Town Glassworks. Old gnome artificer forges, a glass-
capped astronomical observatory, crystalline statues, glass
fountains, ornate windows.
```

Підписи карти та scale нижче мають пропуски й шум; вони **unresolved**, до тексту не додані. Первинний текстовий шар сторінки (номер `5`) також збережено. Це `partial_unresolved`, не повністю відновлена сторінка.

Решта 19 сторінок позначено `unresolved`: stylized/рукописні заголовки та карти, неповний або ще не перевірений для імпорту OCR, порожнє розпізнавання Daycare та відсутня мова для Una Notte da Grifoni. Цей статус не означає, що кожна сторінка об'єктивно нечитабельна людиною; він означає, що її OCR не прийнято до входів. Зокрема, Silver Bane має переважно читабельну обкладинку, але пропущений D&D banner, а сама обкладинка не входить у вибраний текст. Рішення й причини наведено для кожної сторінки у review JSON. Дефекти не приховувалися й не виправлялися LLM.

## Нова ревізія без перезапису старих входів

Перебудовано тільки один affected candidate — `pdf_f8d409ea73d3cc0d9ed4`; його файли лежать у `data/extracted/ocr_revisions/windows-v1/`. Перебудовано тільки один selected input — [pdf_f8d409ea73d3cc0d9ed4_p004-007](../data/ocr_revisions/windows-v1/texts/pdf_f8d409ea73d3cc0d9ed4_p004-007.txt).

Нова [manifest-ревізія](../data/ocr_revisions/windows-v1/manifest.jsonl) містить усі 30 записів: один посилається на новий текст, інші 29 — на незмінені базові файли. Text IDs, document IDs, source PDF hashes та splits залишилися тими самими; змінилася ідентичність **вмісту входу**, визначена text hash і manifest hash. Це не нова незалежна пригода.

- Старий hash зміненого входу: `4287e0735da7280fd7510faa6129be63fd87866efccbe057911bb3cceaabf300`.
- Новий hash: `6a1a941489e8d8b5d30664dc8a5631fc5de3a368bda14552d099a1ceebe8b641`.
- Новий manifest hash: `2deaedfd5b6fd9e13e55814c7d5a53b004f06da114a3dbf9c5d2926103bb73e1`.

Базові `data/manifest.jsonl`, `data/texts/`, `data/selection.json`, `data/splits.json`, original extraction candidates і старі preparation reports не змінювалися. Hashes усіх 40 PDF і 30 базових входів повторно перевірено. Результат — [ocr_integrity_check.json](../data/ocr_integrity_check.json).

У поточному репозиторії не знайдено reviewed golden JSON або модельних experiment results. Жодні labels чи результати не перезаписувалися. Базові артефакти залишаються дійсними для своєї старої ревізії. Для майбутніх вимірювань змінений corpus-вхід, input lengths, token/cost estimates і dataset identity треба брати з нової ревізії; старий validation report підтверджує тільки старий manifest. Точні попередні counts/lengths у звіті PDF-підготовки залишено як історичні вимірювання, а не непомітно оновлено.

[active_dataset.json](../data/active_dataset.json) створено як спільний hash-locked pointer на нову підготовлену ревізію. Статус `prepared_not_evaluation_frozen` не заявляє, що якісні прогалини знято або експеримент уже проведено. Перезапис іншого існуючого pointer заборонено. Обидва майбутні адаптери мають один раз отримати **той самий tuple** через [src/dataset.py](../src/dataset.py) та передати `InputText.content` без provider-specific OCR/normalization:

```python
from pathlib import Path
from src.dataset import load_snapshot

inputs = load_snapshot(Path.cwd())
# Both future adapters consume these exact same immutable records.
```

Loader перевіряє manifest hash та hashes кожного тексту до повернення immutable snapshot. Адаптери моделей ще не реалізовані; їх виконання тут не заявляється. Прямий запуск loader двічі дав ідентичні 30 записів. Обидва manifests пройшли validator; 23 offline-тести пройшли, включно із захистом джерел/labels, stale reviews, вигаданими OCR-рядками, зміненим зображенням, timeout та hash mismatch.

## Команди PowerShell

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/ocr_fallback.py probe
# Пілот придатності друкованого тексту
.\.venv\Scripts\python.exe -X utf8 scripts/ocr_fallback.py run --document pdf_ba9316a7014feccf4bb6 --page 1 --report data/ocr_pilot_printed.json
# Решта marked pages, повторне використання наявного кешу
.\.venv\Scripts\python.exe -X utf8 scripts/ocr_fallback.py run --report data/ocr_batch.json
# Лише рядки, прийняті у review; ніякого автоматичного заповнення пропусків
.\.venv\Scripts\python.exe -X utf8 scripts/ocr_fallback.py revise --activate
.\.venv\Scripts\python.exe -X utf8 scripts/prepare_data.py validate --manifest data/ocr_revisions/windows-v1/manifest.jsonl
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
```

## Відсутній італійський OCR

Для англійського fallback нічого не встановлювалося. Для окремої італійської сторінки потрібен Windows language OCR capability. Нижче **інструкції користувачу, а не виконані команди**: у PowerShell, запущеному від адміністратора, перевірити та за потреби додати capabilities:

```powershell
Get-WindowsCapability -Online -Name 'Language.Basic~~~it-IT~0.0.1.0'
Get-WindowsCapability -Online -Name 'Language.OCR~~~it-IT~0.0.1.0'
# Виконувати відповідний Add тільки якщо State = NotPresent
Add-WindowsCapability -Online -Name 'Language.Basic~~~it-IT~0.0.1.0'
Add-WindowsCapability -Online -Name 'Language.OCR~~~it-IT~0.0.1.0'
```

Це стандартний механізм Microsoft [Add-WindowsCapability](https://learn.microsoft.com/en-us/powershell/module/dism/add-windowscapability?view=windowsserver2025-ps); назву `Language.OCR~~~it-it~0.0.1.0` наведено в офіційному [переліку optional content](https://learn.microsoft.com/it-it/windows/deployment/update/optional-content). Не змінювати security settings або політику виконання скриптів. Якщо Windows Update недоступний, потрібне відповідне офіційне Features on Demand джерело для встановленої версії Windows; інсталяція не вважається успішною без перевірки capability і `probe`.

Після появи `it-IT` у `probe` повторити тільки цю сторінку в **новому** каталозі, щоб не перезаписати попередній unresolved evidence:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/ocr_fallback.py run --document pdf_7a2ed7e7a7d2d48c4045 --page 1 --output data/ocr/windows-it-v1 --report data/ocr_italian_retry.json
```

Італійський OCR у цьому кроці не запускався. Новий результат потребуватиме окремого review та нової dataset-ревізії; заморожені входи й reviewed labels залишаються незмінними.
