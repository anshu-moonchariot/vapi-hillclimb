# Vapi Voice Agent Optimizer

ML-driven system that automatically improves a Vapi dental receptionist agent through iterative prompt optimization, evaluated using real Vapi voice calls.

**Use case:** Dental office appointment scheduler (chosen from the provided options).

**Vapi credits:** Credits on the account used for this work **ran out** before the final runs; additional Vapi usage requires a funded API key. The take-home allows requesting extra credits from Vapi if needed.

---

## Deliverables

| Deliverable | Location |
|---|---|
| Working code | `src/vapi_takehome/` — see [Usage](#usage) |
| ML approach + tradeoffs | [ML Approach](#ml-approach) section below |
| Before/after results | [Results](#results) section + `results/evaluation_report.md` |
| Full step-by-step analysis | `results/evaluation_report.md` |

---

## Results

### Voice Call Baseline (Primary — Real Phone Calls)

| Persona | Turns | Booked | Score |
|---|---|---|---|
| simple_booking | 5 | ✓ | 0.716 |
| reschedule | 2 | ✗ | 0.025 |
| insurance_confused | 6 | ✗ | 0.149 |
| impatient | 4 | ✓ | 0.904 |
| bad_date | 4 | ✓ | 0.904 |
| **Mean** | | | **0.540 ± 0.378** |

Scores are blended: 80% LLM judge (5-dimension rubric) + 20% hard slot-check from `analysisPlan.structuredData`.

The optimizer was initialized with this baseline before hitting Vapi's **daily outbound call limit on free numbers** (~7 calls/day). Iteration 1 showed a candidate with a score of 0.568 (+0.028), indicating the mutation direction was already promising.

### Chat-Based Optimization (Reference — Unlimited, No Voice)

Using the same rubric against the Vapi Chat API (no phone calls, no STT/TTS):

| Stage | Score |
|---|---|
| Baseline | 0.828 |
| After 2 accepted iterations | **0.974** |
| Improvement | **+17.6%** |

This run completed fully and demonstrates that the hill-climbing optimizer converges correctly.

---

## ML Approach

### Algorithm: LLM-guided hill-climbing (prompt mutation)

The core problem is a **black-box optimization** over the space of natural language system prompts. The objective function — conversational quality of a voice agent — is non-differentiable and expensive to evaluate (each sample is a full phone call or multi-turn chat). This rules out gradient-based methods and makes stochastic search appropriate.

**Hill-climbing** with LLM-generated mutations is the right fit because:
- The search space (system prompts) is discrete and high-dimensional; random perturbations are meaningless, but an LLM can generate semantically meaningful variations given a failure analysis
- The objective is noisy (LLM judge variance); a formal acceptance threshold (δ) prevents accepting noise as signal
- It is sample-efficient: each iteration tests only K=3 candidates, and early stopping limits total evaluations

### Optimization loop

```
best_prompt ← baseline_prompt
best_score  ← evaluate(best_prompt, N rollouts)
plateau_count ← 0

for t in 1..T:
    weakness_report ← analyze_failures(rollout_transcripts)
    candidates ← mutator_llm(best_prompt, weakness_report, K=3)

    for candidate in candidates:
        score ← evaluate(candidate, N rollouts)
        if score > best_score + δ:
            best_prompt, best_score ← candidate, score
            plateau_count ← 0
            break

    else:
        plateau_count += 1
        if plateau_count >= 2:
            break  # converged
```

Hyperparameters: `N=5` rollouts, `K=3` candidates, `T=5` max iterations, `δ=0.03`.

### Mutator design

The LLM mutator receives:
1. The current system prompt
2. A structured failure report — which personas scored low and on which dimensions
3. The rubric definitions — so it understands what each dimension penalises

It returns K candidate prompts that each attempt to address identified weaknesses while preserving what is already working. Mutations are constrained to be minimal and targeted, not wholesale rewrites, to avoid regressing strong dimensions while fixing weak ones.

### Evaluation (hybrid scoring)

Every rollout is scored using a two-layer approach:

**Soft (80%) — LLM judge against `rubric/v1.md`:**

| Dimension | Weight | What it checks |
|---|---|---|
| task_completion | 35% | Were all 4 slots collected? (name, date, procedure, contact) |
| turn_efficiency | 20% | Booking completed without wasted turns or repetition? |
| graceful_handling | 20% | Vague, confused, or off-topic inputs handled smoothly? |
| tone_naturalness | 15% | Sounds like a real receptionist? |
| error_recovery | 10% | Recovered from contradictory or impossible inputs? |

**Hard (20%) — `analysisPlan.structuredData` slot-check:**  
Vapi's `analysisPlan` extracts structured JSON from every call. The hard check counts how many of `patient_name`, `appointment_date`, `procedure`, `contact_info` were filled, and halves the score if `appointment_booked=false`. This grounds the subjective judge score in objective, verifiable evidence.

Final score: `0.8 × soft_judge + 0.2 × hard_slots`

### Synthetic test harness

Rather than using real patients, 5 LLM-driven personas simulate different caller types. Each persona is a separate Vapi assistant with a custom system prompt describing their personality and goals, attached to an inbound phone number. This allows deterministic coverage of known failure modes across every optimization iteration.

### Why not other approaches?

| Alternative | Why not used |
|---|---|
| Bayesian optimisation | Requires a parameterised, low-dimensional search space; prompt space is unstructured |
| Reinforcement learning | Needs orders of magnitude more samples; impractical with voice calls costing ~90s each |
| Genetic algorithms | Crossover of prompts produces incoherent text; LLM mutation is more semantically valid |
| Fine-tuning the base model | Out of scope and overkill for prompt-level optimisation |

### Tradeoffs

| Tradeoff | Impact | Mitigation |
|---|---|---|
| LLM judge variance | Same transcript can score differently across runs | Average over N=5 rollouts; use δ threshold to reject noise |
| Voice call cost/time | ~90s per call; full voice run = N×K×T = 75 calls (~112 min) | Chat mode bypasses PSTN for unlimited, fast iteration |
| Prompt-only optimisation | Temperature, voice, STT settings left unchanged | Mutator can be extended to propose any assistant config field |
| No tools in the agent | Reschedule/cancel requires real calendar access | Out of scope; documented as a known gap |

---

## Architecture

```
POST /call (receptionist outbound)
    ↓ Vapi connects to destination number
GET /call/{id} poll → in-progress → ended
    ↓
artifact.transcript + artifact.messages + artifact.recordingUrl
analysisPlan → call.analysis.structuredData (slot extraction)
    ↓
LLM judge (OpenRouter) → ScoreBreakdown
    ↓
Hill-climbing mutator (OpenRouter) → new system prompt candidates
    ↓
PATCH /assistant/{id} → next iteration
```

Both sides of each call are Vapi assistants:
- **Receptionist** (outbound): `firstMessage` + `firstMessageMode=assistant-speaks-first` + `endCallFunctionEnabled=true` + `analysisPlan`
- **Patient** (inbound): persona-specific LLM, attached to destination phone number via `PATCH /phone-number/{id}`

---

## Tools Used

| Tool | Role |
|---|---|
| **Vapi API** | Voice agent creation, real PSTN calls, chat turns, phone number management, structured data extraction via `analysisPlan` |
| **OpenRouter** (gpt-4o-mini) | LLM judge, prompt mutator, synthetic patient in chat mode |
| **Python / httpx** | HTTP client — timeout- and retry-aware, 429 back-off |
| **Conda + uv** | Environment management and fast package installation |
| **Cursor** | AI-assisted development environment used throughout |
| **Twilio** | Provisioned the inbound patient-side phone number |

---

## Setup

### Prerequisites

- Python 3.11+
- [Conda](https://docs.conda.io) (Miniconda is enough)
- [uv](https://docs.astral.sh/uv/) — `brew install uv` on macOS, or `pip install uv`
- A [Vapi](https://vapi.ai) account and API key
- An [OpenRouter](https://openrouter.ai) API key

### 1. Clone the repository

```bash
git clone https://github.com/anshu-moonchariot/vapi-hillclimb.git
cd vapi-hillclimb
```

To use SSH or a fork, use the URL from the repo’s **Code** button instead. If you received the project as a zip, unpack it and `cd` into the folder that contains `pyproject.toml`.

### 2. Install dependencies

```bash
conda create -n vapi-takehome python=3.11 -y
conda activate vapi-takehome
uv pip install -e .
```

### 3. Environment variables

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

| Variable | Required | Where to get it |
|----------|----------|-------------------|
| `VAPI_API_KEY` | Yes | Vapi dashboard → API keys |
| `OPENROUTER_API_KEY` | Yes | OpenRouter → Keys |

All other entries in `.env.example` have working defaults (see file). Variable names match `src/vapi_takehome/config.py` (`N`, `K`, `T`, `DELTA`, not alternate names).

### 4. Voice mode only (`--mode voice`)

Set `VOICE_ENABLED=true` and fill `VAPI_PHONE_NUMBER_ID`, `PATIENT_PHONE_NUMBER_ID`, and `TEST_DESTINATION_E164` (E.164, e.g. `+15551234567`). Provision numbers in the Vapi dashboard. Free numbers have a low daily outbound cap; plan accordingly or wait for the UTC reset.

### 5. Smoke test

```bash
python -m vapi_takehome.cli baseline --n 5 --mode chat
```

This exercises Vapi Chat + OpenRouter only; no phone numbers required.

---

## Usage

```bash
conda activate vapi-takehome

# Recommended: chat mode (no PSTN; works with .env only)
python -m vapi_takehome.cli baseline --n 5 --mode chat
python -m vapi_takehome.cli optimize --mode chat
# Replace the run id with the optimize_* folder name under runs/ (example below)
python -m vapi_takehome.cli final-eval --run-id optimize_20260414T104603 --mode chat

# Voice: real phone calls (requires VOICE_ENABLED + phone IDs in .env)
python -m vapi_takehome.cli baseline --n 5 --mode voice
python -m vapi_takehome.cli optimize --mode voice

# Utilities
python -m vapi_takehome.cli spike
python -m vapi_takehome.cli judge-check
python -m vapi_takehome.cli report --run-id baseline_20260414T104422
```

The `report` and `final-eval` run ids must match a directory under `runs/`. List them with `ls runs/`.

---

## Files

| Path | Description |
|---|---|
| `src/vapi_takehome/vapi_client.py` | Vapi API client — create/update assistants, POST /call, poll GET /call/{id} |
| `src/vapi_takehome/harness.py` | Voice call harness — patient assistant setup, call rollout, artifact extraction |
| `src/vapi_takehome/evaluation.py` | LLM judge + hard slot-check blending |
| `src/vapi_takehome/optimizer.py` | Hill-climbing loop, mutator, baseline/final eval |
| `src/vapi_takehome/rubric/v1.md` | 5-dimension evaluation rubric |
| `src/vapi_takehome/personas/*.yaml` | Patient personas for synthetic caller |
| `prompts/baseline_system.txt` | Starting (deliberately weak) system prompt |
| `results/voice_examples.md` | Call transcripts + structured data from baseline |
| `results/voice_baseline_scores.csv` | Per-persona scores |
| `results/evaluation_report.md` | Full step-by-step analysis with all results |
| `_notes/design_plan.md` | Full design document |
| `_notes/api_notes.md` | Vapi + OpenRouter API reference notes |
