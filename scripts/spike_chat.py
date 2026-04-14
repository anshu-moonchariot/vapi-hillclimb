"""
Phase 1 spike: validates the full pipeline end-to-end before any packaging.
  P1.1 — Create a Vapi assistant
  P1.2 — Run a multi-turn chat conversation (scripted user turns)
  P1.3 — Score the transcript with an OpenRouter judge
  P1.5 — Write runs/spike/GATE_PASSED on success

Run from repo root:
  conda run -n vapi-takehome python scripts/spike_chat.py
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import OpenAI

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

VAPI_BASE = os.environ["VAPI_BASE_URL"].rstrip("/")
VAPI_KEY = os.environ["VAPI_API_KEY"]
OR_BASE = os.environ["OPENROUTER_BASE_URL"].rstrip("/")
OR_KEY = os.environ["OPENROUTER_API_KEY"]
OR_MODEL = (
    os.environ.get("OPENROUTER_MODEL_JUDGE")
    or os.environ.get("OPENROUTER_MODEL_DEFAULT")
    or "openai/gpt-4o"
)

SPIKE_DIR = ROOT / "runs" / "spike"
SPIKE_DIR.mkdir(parents=True, exist_ok=True)

VAPI_HEADERS = {
    "Authorization": f"Bearer {VAPI_KEY}",
    "Content-Type": "application/json",
}

TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=5.0)

# ---------------------------------------------------------------------------
# Minimal baseline prompt (spike-quality; real baseline written in P5.1)
# ---------------------------------------------------------------------------
SPIKE_SYSTEM_PROMPT = """\
You are a receptionist at Bright Smile Dental. Your job is to help patients 
book appointments. Ask for: patient name, preferred date, and the type of 
procedure needed. Be concise and professional.
"""

# ---------------------------------------------------------------------------
# P1.1 — Create assistant
# ---------------------------------------------------------------------------

def create_assistant(client: httpx.Client) -> str:
    print("P1.1 — Creating Vapi assistant...")
    body = {
        "name": "Spike Dental Scheduler",
        "model": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "systemPrompt": SPIKE_SYSTEM_PROMPT,
        },
    }
    r = client.post(f"{VAPI_BASE}/assistant", json=body, headers=VAPI_HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    assistant_id = data["id"]
    print(f"  assistant_id: {assistant_id}")
    (SPIKE_DIR / "assistant_id.txt").write_text(assistant_id)
    return assistant_id


# ---------------------------------------------------------------------------
# P1.2 — Multi-turn chat (scripted user turns, no OpenRouter for caller)
# ---------------------------------------------------------------------------
SCRIPTED_TURNS = [
    "Hi, I'd like to book a dental appointment.",
    "My name is Sarah Chen.",
    "I'm thinking next Tuesday, maybe around 10am?",
    "I need a routine cleaning.",
    "My phone number is 555-867-5309.",
]

def run_chat(client: httpx.Client, assistant_id: str) -> list[dict]:
    print("P1.2 — Running multi-turn chat...")
    messages = []
    previous_chat_id = None

    for i, user_msg in enumerate(SCRIPTED_TURNS):
        print(f"  turn {i+1}: user → {user_msg!r}")
        body = {
            "assistantId": assistant_id,
            "input": user_msg,
        }
        if previous_chat_id:
            body["previousChatId"] = previous_chat_id

        r = client.post(f"{VAPI_BASE}/chat", json=body, headers=VAPI_HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()

        previous_chat_id = data["id"]
        assistant_reply = data["output"][0]["content"] if data.get("output") else ""
        print(f"  turn {i+1}: assistant → {assistant_reply[:80]!r}{'...' if len(assistant_reply) > 80 else ''}")

        messages.append({"role": "user", "content": user_msg})
        messages.append({"role": "assistant", "content": assistant_reply})
        time.sleep(0.5)  # gentle rate limiting

    transcript_path = SPIKE_DIR / "chat_transcript.json"
    transcript_path.write_text(json.dumps({"messages": messages, "assistant_id": assistant_id}, indent=2))
    print(f"  saved → {transcript_path}")

    assert all(m["content"] for m in messages if m["role"] == "assistant"), \
        "One or more assistant turns returned empty content — check API response shape"
    return messages


# ---------------------------------------------------------------------------
# P1.3 — OpenRouter judge
# ---------------------------------------------------------------------------
JUDGE_SYSTEM = """\
You are evaluating a dental office scheduling conversation.
Score the ASSISTANT's performance on the following dimensions (each 0.0–1.0):

- task_completion: Did the assistant collect name, appointment date/time, procedure type, and contact info?
- turn_efficiency: Was the booking completed without unnecessary repetition? (1.0 = very efficient, 0.0 = very repetitive)
- graceful_handling: Did the assistant handle all patient inputs gracefully without getting confused?
- tone_naturalness: Did the assistant sound like a natural receptionist (not robotic)?
- error_recovery: Did the assistant recover well from any confusing or unexpected inputs?

Respond with ONLY valid JSON matching exactly this schema:
{
  "task_completion": <float 0-1>,
  "turn_efficiency": <float 0-1>,
  "graceful_handling": <float 0-1>,
  "tone_naturalness": <float 0-1>,
  "error_recovery": <float 0-1>,
  "aggregate": <weighted average: task_completion*0.35 + turn_efficiency*0.20 + graceful_handling*0.20 + tone_naturalness*0.15 + error_recovery*0.10>,
  "reasoning": "<one sentence>"
}
"""

WEIGHTS = {
    "task_completion": 0.35,
    "turn_efficiency": 0.20,
    "graceful_handling": 0.20,
    "tone_naturalness": 0.15,
    "error_recovery": 0.10,
}

def judge_transcript(messages: list[dict]) -> dict:
    print(f"P1.3 — Judging transcript with OpenRouter ({OR_MODEL})...")
    or_client = OpenAI(api_key=OR_KEY, base_url=OR_BASE)

    transcript_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in messages
    )
    user_content = f"<transcript>\n{transcript_text}\n</transcript>\n\nScore this conversation."

    scores = []
    for attempt in range(2):
        resp = or_client.chat.completions.create(
            model=OR_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": user_content},
            ],
        )
        raw = resp.choices[0].message.content
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"  WARN: JSON parse failed on attempt {attempt+1}: {e}\n  raw: {raw[:200]}")
            raise

        # Recompute aggregate from parts to validate
        dims = [k for k in WEIGHTS]
        recomputed = sum(parsed.get(k, 0) * w for k, w in WEIGHTS.items())
        parsed["_recomputed_aggregate"] = round(recomputed, 4)
        scores.append(parsed)
        print(f"  attempt {attempt+1}: aggregate={parsed.get('aggregate'):.3f}, recomputed={recomputed:.3f}")

    # Variance check
    delta = abs(scores[0].get("aggregate", 0) - scores[1].get("aggregate", 0))
    print(f"  judge variance (aggregate): {delta:.4f}", "(OK)" if delta <= 0.1 else "(WARN: high variance)")

    result = {
        "run_1": scores[0],
        "run_2": scores[1],
        "variance": round(delta, 4),
        "model": OR_MODEL,
    }
    path = SPIKE_DIR / "judge_result.json"
    path.write_text(json.dumps(result, indent=2))
    print(f"  saved → {path}")
    return result


# ---------------------------------------------------------------------------
# P1.5 — Write gate file
# ---------------------------------------------------------------------------

def write_gate():
    gate = SPIKE_DIR / "GATE_PASSED"
    gate.write_text(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "note": "All spike steps passed. Safe to proceed to Phase 2.",
    }, indent=2))
    print(f"\nGATE PASSED → {gate}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Vapi Takehome — Phase 1 Spike")
    print("=" * 60)

    with httpx.Client() as client:
        try:
            assistant_id = create_assistant(client)
            messages = run_chat(client, assistant_id)
        except httpx.HTTPStatusError as e:
            print(f"\nFATAL HTTP error: {e.response.status_code}")
            print(e.response.text[:500])
            sys.exit(1)

    try:
        judge_result = judge_transcript(messages)
    except Exception as e:
        print(f"\nFATAL judge error: {e}")
        sys.exit(1)

    write_gate()
    print("\nSpike complete. Summary:")
    print(f"  assistant_id : {assistant_id}")
    agg = judge_result["run_1"].get("aggregate", "?")
    print(f"  judge score  : {agg}")
    print(f"  transcript   : {SPIKE_DIR / 'chat_transcript.json'}")


if __name__ == "__main__":
    main()
