# Design Plan — Vapi Voice Agent Optimizer

## Use case
Dental office appointment scheduler.

## Architecture
LLM-guided hill-climbing optimization over the assistant's system prompt.

```
baseline_prompt → Vapi assistant → Chat API
                                        ↓
synthetic patient (OpenRouter) → conversation turns
                                        ↓
                              LLM judge (rubric v1)
                                        ↓
                              accept/reject policy
                                        ↓
              LLM mutator (current prompt + failure excerpts)
                                        ↓
                              K candidate prompts → repeat
```

## Key decisions
- **Test harness:** Vapi Chat API (text) for speed; voice smoke tests optional
- **Auxiliary LLMs:** OpenRouter (OpenAI-compatible); one model ID for caller/judge/mutator or separate per role
- **Optimization target:** System prompt only (highest leverage, lowest eval cost)
- **ML method:** Sequential greedy hill-climbing with LLM-proposed mutations
- **Two assistant IDs:** `BASELINE_ASSISTANT_ID` (never patched) and `OPTIMIZER_ASSISTANT_ID` (updated each candidate)

## Evaluation rubric (v1)

| Dimension | Weight |
|-----------|--------|
| task_completion | 0.35 |
| turn_efficiency | 0.20 |
| graceful_handling | 0.20 |
| tone_naturalness | 0.15 |
| error_recovery | 0.10 |

## Hyperparameters
- N=5 rollouts per variant
- K=3 mutations per iteration
- T=5 max iterations
- delta=0.01 acceptance threshold
- Plateau stop: 2 consecutive rejected iterations

## Results achieved
- Baseline: 0.828 ± 0.167
- Final: 0.974 ± 0.037
- Improvement: +17.6% in 2 accepted iterations

## Tradeoffs
- Chat vs voice: text loop is faster but doesn't capture TTS/STT artifacts
- N=5: high variance; production needs N≥20
- Hill-climbing: can miss global optima
- LLM judge: not human-calibrated

See `README.md` for full usage documentation.
