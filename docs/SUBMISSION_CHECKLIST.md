# Submission checklist для mentor review — 02.11.2026

## Зміст і перевірене evidence

- [x] Прочитати [requirement audit](HW1_AUDIT.md): кожна вимога має статус, path та evidence.
- [x] Додати актуальні `README.md`, `REPORT.md`, `docs/HW1_REQUIREMENTS.md`, `docs/HW1_AUDIT.md`, `docs/EVALUATION.md`, `docs/ANNOTATION_GUIDE.md`, schema export та progress.
- [x] Підготувати `src/`, `main.py`, `config.json`, `scripts/`, `tests/`, `pyproject.toml`, `uv.lock`, `.python-version`, `.gitattributes`, `.gitignore`, `.env.example`. Secret credentials у прикладі порожні.
- [x] Prompts v1/v2, fixed repair та changelog; не підміняти frozen LF/CRLF bytes.
- [x] 30 finalized inputs, active/base manifests, selection/splits, active OCR revision із потрібними texts/candidate metadata, десять reviewed labels та status, frozen snapshot; збережено provenance/OCR reports. Templates окремо від labels.
- [x] Два raw run directories: `hw1_baseline_20261101_v1_ab` і `hw1_final_20261101_v2_ab`, включно з failed records, усіма intent/raw/validation files та checksums.
- [x] Final metadata/summary/matrix refs, original evaluation та `mentor_audit_20261102` offline evaluation; 8×30 records, 64 field metrics rows, actual disagreement examples. Auxiliary smoke/warm-up відокремлено.
- [x] Зберегти cumulative `results/budget.sqlite3`, budget adjustments і відповідні raw attempts для узгодження cost/history; не обнуляти homework budget при пакуванні. Actual invoice позначений unknown.
- [x] Tests 129 PASS (із документованим TEMP workaround), dataset/golden validation, dry-run 240/0 calls, offline re-evaluation і portable copy PASS. Перевірки не запускали новий paid benchmark.

## Перед фактичною передачею — manual gate

- [ ] Узгодити права на передачу 30 source texts, PDF excerpts, labels і raw responses. `data/raw/`, `data/extracted/`, `data/ocr/` за замовчуванням НЕ включати; для source-level provenance validation PDF передавати окремо лише за дозволом. Source download URLs та частина author evidence невідомі.
- [ ] Переглянути п'ять golden hooks >40 words, title/role ambiguity, accepted OCR lines. Поточні annotations/метрики для review не міняти; погоджене виправлення — нова revision, snapshot і відповідні reruns/re-evaluation, не «косметика».
- [ ] Звірити фактичний provider invoice/free quota з estimate $0.1356978. Зафіксований application remaining cap $4.8643022 не є підтвердженим provider credit balance.
- [ ] Скласти explicit список передаваних файлів і перевірити, що actual project/evidence включені: **зараз вони переважно untracked**, а HEAD має legacy tracked PDFs з deleted робочими paths. Передача самого HEAD не відтворить цей working tree. Не відновлювати/видаляти старі матеріали автоматично.
- [ ] Виключити `.env` і variants, `.venv`, `.tools` (з portable copy/test caches), `.pytest_cache`, `__pycache__`, логи з невідомими secrets. Перевірити весь кінцевий пакет ще раз. Audit не знайшов exact current configured secrets у 1 390 candidate files і 1 197 reachable history blobs; це не універсальна гарантія щодо невідомих старих credentials.
- [ ] Переконатися, що `.gitattributes` включено до пакета/майбутнього checkout; не запускати EOL renormalization frozen artifacts. Якщо Git уже змінив bytes, відновлювати погоджену revision, не оновлювати hashes/stamps для обходу gate.
- [ ] На машині ментора виконати `uv sync --locked` і README offline commands; today portable test використовував існуючий Python env, не clean OS. Full online run для review не потрібний.
- [ ] За потреби Git submission окремо переглянути `git status`, staging і доступність матеріалів у final commit/archive. **На цьому audit кроці stage/commit/push і відправлення третім особам НЕ виконувалися.**

## Швидкий маршрут ментора

1. [REPORT](../REPORT.md) → результати, чотири actual errors із source/result refs, choice та limitations.
2. [Audit](HW1_AUDIT.md) → completion/partial statuses і перевірені команди.
3. [README](../README.md) → setup і offline evaluation без credentials/PDF/Ollama.
4. [Field CSV](../results/evaluations/mentor_audit_20261102/field_metrics.csv), [disagreements](../results/evaluations/mentor_audit_20261102/disagreements.jsonl), [machine audit](../results/audits/mentor_20261102/audit.json).

**Підсумок:** матеріал для review підготовлено локально; ручні gates вище лишаються відкритими. Експериментальна матриця повна, semantic/rights/packaging обмеження не приховано.
