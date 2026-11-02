# Offline evaluation

Status: complete

No model calls. Smoke excluded. Missing/skipped/failed golden fields count as incorrect.

| Provider / model | Prompt | Sampling | Status | Attempted | Success | Failed | Missing | Skipped | Mean field accuracy |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| openai / gpt-4o-mini | v1 | A | complete | 30 | 30 | 0 | 0 | 0 | 0.2875 |
| openai / gpt-4o-mini | v1 | B | complete | 30 | 30 | 0 | 0 | 0 | 0.2875 |
| openai / gpt-4o-mini | v2 | A | complete | 30 | 30 | 0 | 0 | 0 | 0.2875 |
| openai / gpt-4o-mini | v2 | B | complete | 30 | 30 | 0 | 0 | 0 | 0.3000 |
| ollama / qwen2.5:3b | v1 | A | complete | 30 | 27 | 3 | 0 | 0 | 0.1875 |
| ollama / qwen2.5:3b | v1 | B | complete | 30 | 28 | 2 | 0 | 0 | 0.2000 |
| ollama / qwen2.5:3b | v2 | A | complete | 30 | 27 | 3 | 0 | 0 | 0.2125 |
| ollama / qwen2.5:3b | v2 | B | complete | 30 | 27 | 3 | 0 | 0 | 0.2125 |

Unmeasured combinations have zero correct fields on fixed denominators; these are coverage penalties, not observed model accuracy.

Percentiles: linear interpolation, h=(n-1)*p (Hyndman-Fan type 7). Missing durations are unknown, never zero. Details, costs and failure-only latency: summary.json.
