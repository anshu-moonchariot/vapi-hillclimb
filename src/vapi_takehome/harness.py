"""Voice call harness.

Drives test conversations by placing real Vapi phone calls:
  - The receptionist assistant (being optimized) places an outbound call
  - A synthetic patient assistant answers on the destination number
  - After the call ends, artifacts are retrieved via GET /call/{id}

Public API:
  setup_patient_assistant(client)   — create patient LLM + attach to inbound number
  run_call_rollout(client, ...)     — POST /call, poll, return RolloutResult
"""

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import httpx
import yaml

from vapi_takehome.config import settings
from vapi_takehome.logging_config import get_logger
from vapi_takehome.openrouter import complete_text
from vapi_takehome.vapi_client import (
    attach_inbound_assistant,
    create_assistant,
    create_call,
    get_call,
    poll_call_until_done,
    send_chat_turn,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Persona loading (same YAML files, now used to build the patient assistant)
# ---------------------------------------------------------------------------
_PERSONAS_DIR = Path(__file__).parent / "personas"
_PERSONA_IDS = [
    "simple_booking",
    "reschedule",
    "insurance_confused",
    "impatient",
    "bad_date",
]


def load_persona(persona_id: str) -> dict:
    path = _PERSONAS_DIR / f"{persona_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Persona file not found: {path}")
    return yaml.safe_load(path.read_text())


def all_persona_ids() -> list[str]:
    return _PERSONA_IDS


# ---------------------------------------------------------------------------
# Patient assistant system prompt builder
# ---------------------------------------------------------------------------
PATIENT_SYSTEM_TEMPLATE = """\
You are roleplaying as a patient calling a dental office to make an appointment.

Persona: {description}
Your goal: {goal}
Style constraints:
{style_constraints}

Rules:
- Give SHORT, natural responses (1–3 sentences) — you are on a real phone call
- Provide information as the receptionist asks for it; do not volunteer everything upfront
- Stay in character throughout the entire call
- When all your booking information has been confirmed by the receptionist, politely say goodbye and end the call
- If asked the same question twice, politely point that out
"""


def build_patient_prompt(persona: dict) -> str:
    style = "\n".join(f"- {c}" for c in persona.get("style_constraints", []))
    return PATIENT_SYSTEM_TEMPLATE.format(
        description=persona["description"],
        goal=persona["goal"],
        style_constraints=style,
    )


# ---------------------------------------------------------------------------
# Patient assistant setup (called once per optimization run)
# ---------------------------------------------------------------------------
_patient_assistant_cache: dict[str, str] = {}  # persona_id → assistant_id


def setup_patient_assistant(client: httpx.Client, persona_id: str, run_id: str = "") -> str:
    """Create a patient assistant for this persona and attach it to the inbound number.

    Returns the patient assistant_id. Cached per persona_id for the process lifetime.
    """
    log = get_logger(__name__, run_id)

    if persona_id in _patient_assistant_cache:
        aid = _patient_assistant_cache[persona_id]
        log.info(f"Reusing patient assistant for persona={persona_id}: {aid}")
        # Re-attach in case inbound number lost its binding between process runs
        attach_inbound_assistant(client, settings.patient_phone_number_id, aid)
        return aid

    persona = load_persona(persona_id)
    prompt = build_patient_prompt(persona)
    name = f"Patient-{persona_id}"

    data = create_assistant(client, name, prompt, with_analysis=False)
    patient_id = data["id"]

    # Attach to destination phone number as inbound handler
    attach_inbound_assistant(client, settings.patient_phone_number_id, patient_id)
    log.info(f"Patient assistant {patient_id} attached to inbound number {settings.patient_phone_number_id}")

    _patient_assistant_cache[persona_id] = patient_id
    return patient_id


# ---------------------------------------------------------------------------
# Rollout result
# ---------------------------------------------------------------------------
@dataclass
class RolloutResult:
    messages: list[dict] = field(default_factory=list)
    transcript: str = ""
    recording_url: str = ""
    structured_data: dict = field(default_factory=dict)
    analysis: dict = field(default_factory=dict)
    persona_id: str = ""
    assistant_id: str = ""
    call_id: str = ""
    num_turns: int = 0
    stop_reason: str = ""
    failed: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Main rollout: POST /call → poll → extract artifacts
# ---------------------------------------------------------------------------
def run_call_rollout(
    client: httpx.Client,
    receptionist_assistant_id: str,
    persona_id: str,
    run_id: str = "",
) -> RolloutResult:
    """Place a real Vapi voice call and return a RolloutResult with full artifacts.

    Flow:
      1. Ensure patient assistant for this persona is attached to inbound number
      2. POST /call  (receptionist calls the patient number)
      3. Poll GET /call/{id} until terminal state
      4. Extract transcript, messages, recording, structuredData
    """
    log = get_logger(__name__, run_id)
    log.info(f"Voice rollout starting: persona={persona_id} receptionist={receptionist_assistant_id}")

    result = RolloutResult(persona_id=persona_id, assistant_id=receptionist_assistant_id)

    # Step 1: setup patient assistant (idempotent via cache)
    try:
        setup_patient_assistant(client, persona_id, run_id)
    except Exception as e:
        log.error(f"Failed to set up patient assistant: {e}")
        result.failed = True
        result.error = str(e)
        result.stop_reason = "setup_error"
        return result

    # Step 2: place call
    try:
        call_data = create_call(client, receptionist_assistant_id)
        call_id = call_data["id"]
        result.call_id = call_id
        log.info(f"Call placed: call_id={call_id}")
    except Exception as e:
        log.error(f"POST /call failed: {e}")
        result.failed = True
        result.error = str(e)
        result.stop_reason = "call_error"
        return result

    # Step 3: poll until call ends
    try:
        # Allow call to connect and conversation to play out before first poll.
        # Calls are capped at 120s via maxDurationSeconds; budget 160s total.
        time.sleep(20)
        final = poll_call_until_done(client, call_id, poll_interval=15, max_wait=200)
    except TimeoutError as e:
        log.error(str(e))
        result.failed = True
        result.error = str(e)
        result.stop_reason = "timeout"
        return result
    except Exception as e:
        log.error(f"Polling failed: {e}")
        result.failed = True
        result.error = str(e)
        result.stop_reason = "poll_error"
        return result

    # Step 4: extract artifacts
    artifact = final.get("artifact", {})
    analysis = final.get("analysis", {})

    transcript = artifact.get("transcript", "")
    messages = artifact.get("messages", [])
    recording_url = artifact.get("recordingUrl", "")
    structured_data = analysis.get("structuredData", {})

    result.transcript = transcript
    result.messages = messages
    result.recording_url = recording_url
    result.structured_data = structured_data
    result.analysis = analysis
    result.num_turns = len([m for m in messages if m.get("role") == "user"])
    result.stop_reason = final.get("endedReason", "ended")

    log.info(
        f"Call done: call_id={call_id} turns={result.num_turns} "
        f"recording={'yes' if recording_url else 'no'} "
        f"structured_data={structured_data}"
    )
    return result


# ---------------------------------------------------------------------------
# Chat-based rollout (fallback when voice daily limit is hit)
# ---------------------------------------------------------------------------
_PATIENT_CHAT_SYSTEM = """\
You are roleplaying as a patient calling a dental office to make an appointment.

Persona: {description}
Your goal: {goal}
Style constraints:
{style_constraints}

Rules:
- Give SHORT, natural responses (1-3 sentences)
- Provide information as the receptionist asks; don't volunteer everything upfront
- Stay in character throughout
- When your booking is confirmed, say a brief goodbye and output exactly: [DONE]
- If asked the same question twice, politely note it
"""

_STOP_SIGNALS = {"[done]", "[end]", "[bye]", "goodbye", "thank you, goodbye"}


def run_chat_rollout(
    client: httpx.Client,
    assistant_id: str,
    persona_id: str,
    run_id: str = "",
) -> RolloutResult:
    """Drive a multi-turn Vapi Chat conversation with a synthetic patient caller.

    Uses POST /chat (no phone numbers, no PSTN) — unlimited, fast.
    Returns a RolloutResult with messages and transcript populated.
    """
    log = get_logger(__name__, run_id)
    log.info(f"Chat rollout starting: persona={persona_id} assistant={assistant_id}")

    result = RolloutResult(persona_id=persona_id, assistant_id=assistant_id)
    persona = load_persona(persona_id)

    style = "\n".join(f"- {c}" for c in persona.get("style_constraints", []))
    patient_system = _PATIENT_CHAT_SYSTEM.format(
        description=persona["description"],
        goal=persona["goal"],
        style_constraints=style,
    )

    messages: list[dict] = []
    previous_chat_id: Optional[str] = None
    max_turns = settings.max_turns

    for turn in range(max_turns):
        # Build patient utterance via OpenRouter
        history = "\n".join(
            f"{'RECEPTIONIST' if m['role'] == 'assistant' else 'YOU'}: {m['content']}"
            for m in messages
        )
        patient_prompt = (
            f"{history}\n\nYOUR TURN (respond naturally, 1-3 sentences):"
            if history else "Start by briefly stating why you are calling."
        )
        try:
            patient_text = complete_text(
                system=patient_system,
                messages=[{"role": "user", "content": patient_prompt}],
            ).strip()
        except Exception as e:
            log.error(f"OpenRouter patient error turn={turn}: {e}")
            result.failed = True
            result.error = str(e)
            result.stop_reason = "openrouter_error"
            break

        messages.append({"role": "user", "content": patient_text})

        # Send to Vapi Chat
        try:
            resp = send_chat_turn(client, assistant_id, patient_text, previous_chat_id)
        except Exception as e:
            log.error(f"Vapi chat error turn={turn}: {e}")
            result.failed = True
            result.error = str(e)
            result.stop_reason = "vapi_error"
            break

        previous_chat_id = resp.get("id") or resp.get("chatId") or previous_chat_id

        output = resp.get("output", [])
        assistant_text = ""
        for item in output:
            if item.get("role") == "assistant":
                content = item.get("content", "")
                if isinstance(content, str):
                    assistant_text += content
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            assistant_text += block.get("text", "")
                        elif isinstance(block, str):
                            assistant_text += block
        if not assistant_text:
            assistant_text = str(output)

        messages.append({"role": "assistant", "content": assistant_text})

        # Check stop signal
        if any(sig in patient_text.lower() for sig in _STOP_SIGNALS):
            result.stop_reason = "patient_done"
            break
        if any(sig in assistant_text.lower() for sig in {"goodbye", "thank you for calling", "have a great day"}):
            result.stop_reason = "receptionist_closed"
            break
    else:
        result.stop_reason = "max_turns"

    result.messages = messages
    result.num_turns = sum(1 for m in messages if m["role"] == "user")
    result.transcript = "\n".join(
        f"{'PATIENT' if m['role'] == 'user' else 'RECEPTIONIST'}: {m['content']}"
        for m in messages
    )
    log.info(f"Chat rollout done: persona={persona_id} turns={result.num_turns} stop={result.stop_reason}")
    return result
