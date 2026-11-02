# Prompt changelog

## v1 — 2026-10-31

Initial source-only baseline aligned with the shared AdventureCard schema and
annotation rules. Separates system instructions from untrusted document data,
requires explicit missing values, and excludes unsupported inference. No model
execution or quality measurements informed this initial version; no golden
answers are included. Version v2 remains a later milestone.

## Shared repair v1 — 2026-11-01

Added fixed `repair_v1.txt`, shared across extraction versions. Receives source,
invalid answer and validation errors as untrusted data; uses the same strict
schema and source-only rules. Verified with synthetic mocks; no live calls.
Extraction v2 is still absent and is reported as a prerequisite, never replaced
silently with v1.

## Extraction v2 — 2026-11-01 (development evidence only; not measured)

Scope: same AdventureCard task, eight required keys, schema, models, A/B settings,
and fixed `repair_v1.txt`. V1 and repair are preserved byte-for-byte. This entry
supersedes the earlier historical statement that v2 was absent. V2 contains
instructions only: no adventure names, entity answers, example cards, labels,
or baseline outputs copied into the extraction prompt.

Only the three designated development inputs and their **12 v1 terminal
results** in `hw1_baseline_20261101_v1_ab` were opened for prompt design. Eleven
results contain cards; Festival/Ollama A is a transport failure, not an invented
semantic error. Input hashes match the active manifest and all twelve results
reference the current unchanged v1 hash. No golden answer files, golden result
cards, evaluation disagreements, or checkpoint error examples were opened to
design v2. This is source-grounding inspection, not creation of reviewed labels.

### Development evidence index

Text IDs and PDF pages:

- **D1** `pdf_7a2ed7e7a7d2d48c4045_p002-008` —
  [Una Notte da Grifoni, PDF pp.2–8](../data/texts/pdf_7a2ed7e7a7d2d48c4045_p002-008.txt).
- **D2** `pdf_5dcfc61ef86267e75e59_p001-007` —
  [Witchlight Beer Festival, PDF pp.1–7](../data/texts/pdf_5dcfc61ef86267e75e59_p001-007.txt).
- **D3** `pdf_5e5c8a49a5768666500a_p001-011` —
  [Adventures Daycare, PDF pp.1–11](../data/texts/pdf_5e5c8a49a5768666500a_p001-011.txt).

Each linked result supplies the full job/result ID; short labels below are just
references, not new data IDs. All paths are under the same immutable v1 run.

| Input | OpenAI A | OpenAI B | Ollama A | Ollama B |
|---|---|---|---|---|
| D1 | [a8a5d4f8](../results/runs/hw1_baseline_20261101_v1_ab/jobs/a8a5d4f80dfdb7eb6cd9b1a1f8f435ab07c2948ebcf670150b6b78f9e2083391/result.json) | [7a990aac](../results/runs/hw1_baseline_20261101_v1_ab/jobs/7a990aacc84ddee80974605b1c467bd7ed918b6e9061b94c0f79cdeb805e0f8e/result.json) | [01073718](../results/runs/hw1_baseline_20261101_v1_ab/jobs/01073718a3389d53caec7169c6aea0a2004c8f245786caf8aa090c7db9f6d7e5/result.json) | [592d0961](../results/runs/hw1_baseline_20261101_v1_ab/jobs/592d096107619f08be87f7edf7c86de479def0825147fb56affb87688d7158d9/result.json) |
| D2 | [ff26c9f5](../results/runs/hw1_baseline_20261101_v1_ab/jobs/ff26c9f549490d3adbb84b8aeb8774f0d0e29ab1982e25b886fb4bcc1229810b/result.json) | [27751146](../results/runs/hw1_baseline_20261101_v1_ab/jobs/277511467026af9fc71223e1b3419ad71855d0f6c60a46902c27f66b397bc564/result.json) | [14e8c463](../results/runs/hw1_baseline_20261101_v1_ab/jobs/14e8c463c02006ed1131d0d8441a5a73f382ed0d29dd2e2b95f6c5427a530d6b/result.json) | [8548f874](../results/runs/hw1_baseline_20261101_v1_ab/jobs/8548f874114694452dfedeffe79fe65911be2cc58b7b5e46871cfa30e60bf005/result.json) |
| D3 | [2878069c](../results/runs/hw1_baseline_20261101_v1_ab/jobs/2878069c8626925753903c413b7287364aec595eef93a06a37a71471c19fd37b/result.json) | [d32f8a2e](../results/runs/hw1_baseline_20261101_v1_ab/jobs/d32f8a2e6e182bde84e7aee5d1aa9b2fbe71e10fa44991a29b5413e89f0c802b/result.json) | [200158f8](../results/runs/hw1_baseline_20261101_v1_ab/jobs/200158f84134d52e9944cb073f0cada918319af059aa57f294c2a42f7a3e9736/result.json) | [dadfd4a7](../results/runs/hw1_baseline_20261101_v1_ab/jobs/dadfd4a7c7c305fe545be6b0f88a4b938533c3a293d575085460a1f3d6aa3b70/result.json) |

### Changes, observations, hypotheses and tradeoffs

| Change in v2 | Observed source/result evidence | Expected benefit (hypothesis) | Possible tradeoff |
|---|---|---|---|
| Field-local evidence gate; retain only literal phrases, no explanatory properties or generated identifiers | D3 Ollama A adds `a magic bag of holding` and fireball properties to named items; PDF p.8 lists the items and external rule references without those properties. D2 Ollama B outputs `main_stage` and other generated identifiers instead of source wording. | Less external-lore completion and invented prose; source-grounded strings. | More conservative extraction may omit a correct fact when imperfect text obscures support. |
| Explicit level applicability and null/placeholder check | D2 OpenAI A/B return `1st level characters`, but PDF p.1 attaches it to the referenced Mystery Mine, not directly to the festival. D2 Ollama B emits `/recommended_level`. D3 Ollama A invents `party-level 1`; PDF p.4 explicitly instructs creation of a `3rd-level` character. D1 OpenAI B changes the stated player count from `4–5` to `3–5` in its level phrase. | Preserve applicable level evidence; avoid transferring levels, changing numbers, and filling an absent value with a path. | Strict scope checks can yield null where a reader would infer applicability. Do not infer that D3 lacks a level: it explicitly has one. |
| Classify narrative prose separately from names/terms | D1 Ollama A/B classify the Italian narrative as `en`; English setting names and game terms do not support that classification. | Correct language enum without translating source fields. | A short or genuinely mixed input may remain ambiguous; this is not a blanket rule to use `other`. |
| Verify complete-sentence boundaries, reject footers and new summaries | D1 Ollama A/B use a page footer (`... pag. 1`) as hook. D2 Ollama B writes a multi-sentence festival summary; OpenAI B shortens a source sentence. D3 OpenAI A/B turn the setup clause preceding a colon/quoted tale into a new sentence. | One actual qualifying source sentence, unchanged except permitted normalization, or null. | Can increase null hooks; sentence boundaries in OCR/quoted dialogue remain difficult. |
| Whole-input completeness pass for named actors and explicit rooms | D1 OpenAI A/B omit the named offstage antagonist and named fish while the supplied text explicitly gives their current-story roles; later named actors differ between A/B. D2 OpenAI A/B omit the named market merchant Beans (PDF p.3) and performer Glorianna (pp.2/5). D3 Ollama B omits the daycare owner; both local cards replace many explicit rooms with broad floor headings. | Better coverage across later sections, named creatures and offstage actors. | Higher recall can add reference-only figures or optional PCs; existing exclusions still apply. No fixed name list or answer inventory is added to the prompt. |
| Preserve full names with local alias evidence only | D2 Ollama B shortens several source full names to first names. D3 has Talaryl/Taraly spellings in the source itself; cards choose different forms. | Less unjustified shortening; deterministic first-clear-full-name policy already in annotation rules. | Source spelling variants are an ambiguity, not proof the model invented the variant; no global spelling correction or fuzzy merging is introduced. |
| Deduplicate mentions without merging distinct places or conditions | D1 Ollama A repeats `Cavalleria della Guardia` verbatim in locations. D1 Ollama B lists the same described chest both plainly and with an explanatory suffix. | Remove repeated entities without copying near-duplicate restatements. | An aggressive merge could collapse distinct generic rooms/containers; require local identity evidence. |
| Check threat/reward relationships and retain qualifiers | D2 OpenAI A drops the illusion qualifier from the dragon and includes the earlier bounty-hunter squad without its historical context; pp.5–6 distinguish harmless staged illusions and a real ambush. D3 Ollama A lists basement rations/crates as threats; Ollama B adds `Pitiful existence` as a creature and labels a challenge rating as a level. D3 Ollama B lists starting legendary items as rewards, although PDF p.5 assigns them at creation. | Fewer ordinary objects promoted to threats, fewer starting allocations treated as earned loot, and fewer lost conditions. | May reduce recall of conditional dangers/benefits. Searchable toy weapons in D3 are explicitly discoverable on PDF p.6 and must not be blanket-excluded as starting gear. |

No completed dev card was entirely missing all scalar/list information, so no
claim of an observed all-empty-card failure is made. Explicit null/[] rules are
retained from v1; the strengthened placeholder gate is supported specifically by
D2 Ollama B. D2 Ollama A's `local_timeout` provides **no completed card** and no
semantic evidence; v2 is not claimed to repair transport/context failures.

The title/heading filter and final all-keys check retain the existing task. D2
Ollama B appends `Encounter` to the title even though the first clear title on
PDF p.1 lacks that suffix; this supports avoiding descriptive title additions.
No new output fields, evidence fields, numeric output limits or sampling changes
are introduced. V2 is longer than v1, so it consumes more context/prefill and may
worsen latency or local context pressure. Its expanded checklist is a robustness
hypothesis; static checks cannot establish that a model follows it.

**Measurement status:** no v2 generation, improvement claim, new annotation, or
benchmark measurement in this step. Future testing must preserve all failed and
missing examples and distinguish prompt effects from runtime/config changes.
The extraction version is `v2.txt`; the unchanged fixed repair instruction is
not counted as the second extraction version.
