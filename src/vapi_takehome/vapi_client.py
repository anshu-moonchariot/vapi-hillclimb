"""Thin Vapi API client.

Functions:
  create_assistant  — POST /assistant
  update_assistant  — PATCH /assistant/{id}
  send_chat_turn    — POST /chat (one turn)
  create_call       — POST /call (voice; only used if VOICE_ENABLED)
  get_call          — GET /call/{id}
"""

import time
from typing import Any

import httpx

from vapi_takehome.config import settings
from vapi_takehome.logging_config import get_logger

logger = get_logger(__name__)

_TIMEOUT = httpx.Timeout(
    connect=settings.http_connect_timeout,
    read=settings.http_read_timeout,
    write=30.0,
    pool=5.0,
)
_HEADERS = {
    "Authorization": f"Bearer {settings.vapi_api_key}",
    "Content-Type": "application/json",
}
_MAX_RETRIES = 3
_RETRY_STATUSES = {429, 500, 502, 503, 504}


def _request(client: httpx.Client, method: str, path: str, **kwargs) -> dict:
    url = f"{settings.vapi_base_url}{path}"
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            r = client.request(method, url, headers=_HEADERS, timeout=_TIMEOUT, **kwargs)
            if r.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning(f"{method} {path} → {r.status_code}; retrying in {wait}s (attempt {attempt})")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except httpx.TimeoutException:
            if attempt < _MAX_RETRIES:
                logger.warning(f"{method} {path} timed out; retrying (attempt {attempt})")
                time.sleep(2 ** attempt)
            else:
                raise
    raise RuntimeError(f"All retries exhausted for {method} {path}")


ANALYSIS_PLAN = {
    "summaryPrompt": "Summarize this dental office scheduling call in 2-3 sentences.",
    "structuredDataSchema": {
        "type": "object",
        "properties": {
            "appointment_booked": {"type": "boolean", "description": "Was a dental appointment successfully booked or rescheduled?"},
            "patient_name": {"type": "string", "description": "Full name of the patient, if collected"},
            "appointment_date": {"type": "string", "description": "Date and time of the appointment, if collected"},
            "procedure": {"type": "string", "description": "Type of dental procedure requested (e.g. cleaning, filling, emergency)"},
            "contact_info": {"type": "string", "description": "Patient phone number or email, if collected"},
        },
        "required": ["appointment_booked"],
    },
    "structuredDataPrompt": "You are an expert data extractor. Extract scheduling details from this dental office call transcript.",
    "successEvaluationPrompt": "Did the receptionist successfully book or rebook a dental appointment, collecting patient name, preferred date/time, procedure type, and contact info?",
    "successEvaluationRubric": "PassFail",
}


RECEPTIONIST_FIRST_MESSAGE = (
    "Thank you for calling Bright Smile Dental! This is the receptionist. "
    "How can I help you today?"
)


def create_assistant(
    client: httpx.Client,
    name: str,
    system_prompt: str,
    with_analysis: bool = True,
    first_message: str = "",
    first_message_mode: str = "assistant-waits-for-user",
) -> dict:
    """Create a new Vapi assistant. Returns full assistant object."""
    body = {
        "name": name,
        "model": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "systemPrompt": system_prompt,
        },
        "firstMessageMode": first_message_mode,
        "endCallFunctionEnabled": True,
    }
    if first_message:
        body["firstMessage"] = first_message
    if with_analysis:
        body["analysisPlan"] = ANALYSIS_PLAN
    data = _request(client, "POST", "/assistant", json=body)
    logger.info(f"Created assistant id={data['id']} name={name!r}")
    return data


def update_assistant(client: httpx.Client, assistant_id: str, system_prompt: str) -> dict:
    """Patch an existing assistant's system prompt. Returns updated object."""
    body = {
        "model": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "systemPrompt": system_prompt,
        },
        "analysisPlan": ANALYSIS_PLAN,
        "firstMessage": RECEPTIONIST_FIRST_MESSAGE,
        "firstMessageMode": "assistant-speaks-first",
        "endCallFunctionEnabled": True,
    }
    data = _request(client, "PATCH", f"/assistant/{assistant_id}", json=body)
    logger.info(f"Updated assistant id={assistant_id}")
    return data


def attach_inbound_assistant(client: httpx.Client, phone_number_id: str, assistant_id: str) -> dict:
    """Attach an assistant as inbound handler for a Vapi phone number."""
    body = {"assistantId": assistant_id}
    data = _request(client, "PATCH", f"/phone-number/{phone_number_id}", json=body)
    logger.info(f"Attached assistant {assistant_id} → phone number {phone_number_id}")
    return data


def send_chat_turn(
    client: httpx.Client,
    assistant_id: str,
    user_message: str,
    previous_chat_id: str | None = None,
) -> dict:
    """Send one user turn to Vapi chat. Returns response dict with 'id' and 'output'."""
    body: dict[str, Any] = {
        "assistantId": assistant_id,
        "input": user_message,
    }
    if previous_chat_id:
        body["previousChatId"] = previous_chat_id

    data = _request(client, "POST", "/chat", json=body)
    return data


def create_call(client: httpx.Client, assistant_id: str, max_duration: int = 120) -> dict:
    """Place an outbound voice call. Only call when VOICE_ENABLED=true.

    max_duration: hard cap in seconds; prevents runaway calls between two LLM assistants.
    """
    if not settings.voice_enabled:
        raise RuntimeError("create_call called but VOICE_ENABLED=false")
    body = {
        "assistantId": assistant_id,
        "phoneNumberId": settings.vapi_phone_number_id,
        "customer": {"number": settings.test_destination_e164},
        "maxDurationSeconds": max_duration,
    }
    data = _request(client, "POST", "/call", json=body)
    logger.info(f"Created call id={data['id']} maxDurationSeconds={max_duration}")
    return data


def get_call(client: httpx.Client, call_id: str) -> dict:
    """GET /call/{id}. Poll until terminal status."""
    return _request(client, "GET", f"/call/{call_id}")


def poll_call_until_done(
    client: httpx.Client,
    call_id: str,
    poll_interval: int = 15,
    max_wait: int = 360,
) -> dict:
    """Poll GET /call/{id} until terminal state, with 429-aware back-off.

    Starts polling after an initial settling delay, then polls every poll_interval
    seconds. On 429 responses, backs off for 30 s before retrying.
    """
    terminal = {"ended", "failed"}
    elapsed = 0
    while elapsed < max_wait:
        try:
            data = get_call(client, call_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                backoff = 30
                logger.warning(f"429 polling call {call_id}; backing off {backoff}s")
                time.sleep(backoff)
                elapsed += backoff
                continue
            raise

        status = data.get("status", "")
        logger.info(f"Call {call_id} status={status} elapsed={elapsed}s")
        if status in terminal:
            return data
        time.sleep(poll_interval)
        elapsed += poll_interval

    raise TimeoutError(f"Call {call_id} did not reach terminal state within {max_wait}s")
