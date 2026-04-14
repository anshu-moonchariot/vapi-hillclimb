# Vapi Voice Agent Optimizer

ML-driven system that automatically improves a Vapi dental receptionist agent through iterative prompt optimization, evaluated using real Vapi voice calls.

**Use case:** Dental office appointment scheduler (chosen from the provided options).

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

**Algorithm**: LLM-guided hill-climbing (prompt mutation).

Each iteration:
1. An LLM mutator generates K=3 candidate system prompt variants
2. Each candidate is evaluated over N=5 personas via real Vapi voice calls
3. The best candidate's mean score is compared to the current best
4. If improvement > δ=0.03, the prompt is accepted; otherwise the iteration is a plateau
5. Optimization stops after 2 consecutive plateaus (early stopping) or T=5 iterations

**Evaluation** (hybrid):
- **Soft (80%)**: LLM judge scores 5 dimensions — task completion, turn efficiency, graceful handling, tone naturalness, error recovery — against `rubric/v1.md`
- **Hard (20%)**: `analysisPlan.structuredData` checks whether 4 booking slots were filled (`patient_name`, `appointment_date`, `procedure`, `contact_info`) and `appointment_booked=true`

**Why this approach**: Gradient-free optimization is appropriate when the objective is non-differentiable (LLM judge outputs). Hill-climbing with LLM mutations is simple, explainable, and fast enough for prompt-space search.

**Tradeoffs**:
- Voice calls take ~80–120s each; wall-clock time grows linearly with N×K×T
- Vapi free numbers cap at ~7 outbound calls/day; Twilio import removes this limit
- LLM judge variance is managed by running N=5 rollouts and averaging

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

- Conda
- `uv` (`brew install uv`)
- Vapi account with 2 phone numbers provisioned (free tier is fine for chat mode)
- OpenRouter API key

### Install

```bash
git clone <repo-url>
cd vapi_takehome
conda create -n vapi-takehome python=3.11 -y
conda activate vapi-takehome
uv pip install -e .
```

### Environment (`.env`)

```bash
# Vapi
VAPI_API_KEY=<your Vapi secret key>
VAPI_BASE_URL=https://api.vapi.ai

# OpenRouter (judge + mutator + synthetic patient)
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_API_KEY=<your OpenRouter key>
OPENROUTER_MODEL_DEFAULT=openai/gpt-4o-mini

# Voice call infrastructure (only needed for --mode voice)
VOICE_ENABLED=true
VAPI_PHONE_NUMBER_ID=<outbound receptionist number ID>
PATIENT_PHONE_NUMBER_ID=<inbound patient number ID>
TEST_DESTINATION_E164=<patient number in E.164, e.g. +18005551234>

# Optimization hyperparameters (defaults shown)
N_ROLLOUTS=5
K_CANDIDATES=3
T_ITERATIONS=5
DELTA=0.03
```

### Phone number setup (voice mode only)

In the Vapi dashboard, provision 2 free phone numbers:
1. `VAPI_PHONE_NUMBER_ID` — places outbound calls (receptionist side)
2. `PATIENT_PHONE_NUMBER_ID` + `TEST_DESTINATION_E164` — receives calls (patient side)

> **Note**: Free Vapi numbers cap at ~7 outbound calls/day. For the full optimizer (~45 calls), either wait for midnight UTC reset or import a Twilio number via the Vapi dashboard.

---

## Usage

```bash
# Run baseline (5 real voice calls)
python -m vapi_takehome.cli baseline --n 5

# Run hill-climbing optimizer
python -m vapi_takehome.cli optimize

# Quick API spike (no optimization)
python -m vapi_takehome.cli spike

# Validate LLM judge consistency
python -m vapi_takehome.cli judge-check
```

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
| `results/evaluation_report.md` | Full step-by-step analysis with all results || `_notes/design_plan.md` | Full design document |
| `_notes/api_notes.md` | Vapi + OpenRouter API reference notes |
