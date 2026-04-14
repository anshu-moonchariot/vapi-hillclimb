"""Evaluation layer: judge transcripts against rubric v1.

Public API:
  evaluate_transcript(messages) -> ScoreBreakdown
  judge_check(fixture_path)     -> None  (exits non-zero on high variance)
"""

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from vapi_takehome.config import settings
from vapi_takehome.logging_config import get_logger
from vapi_takehome.openrouter import complete_json

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Load rubric once at import time
# ---------------------------------------------------------------------------
_RUBRIC_TEXT = settings.rubric_path.read_text()

JUDGE_SYSTEM = f"""You are an expert evaluator of AI voice assistant conversations.
You will score a dental office scheduling conversation using the rubric below.

{_RUBRIC_TEXT}

IMPORTANT: Respond with ONLY valid JSON matching exactly this schema — no markdown, no prose:
{{
  "task_completion": <float 0.0-1.0>,
  "turn_efficiency": <float 0.0-1.0>,
  "graceful_handling": <float 0.0-1.0>,
  "tone_naturalness": <float 0.0-1.0>,
  "error_recovery": <float 0.0-1.0>,
  "aggregate": <weighted sum per rubric formula>,
  "reasoning": "<one concise sentence explaining the main strength or weakness>"
}}
"""

WEIGHTS = settings.rubric_weights


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class ScoreBreakdown:
    task_completion: float = 0.0
    turn_efficiency: float = 0.0
    graceful_handling: float = 0.0
    tone_naturalness: float = 0.0
    error_recovery: float = 0.0
    aggregate: float = 0.0
    reasoning: str = ""
    failed: bool = False
    error: Optional[str] = None
    rubric_version: str = field(default_factory=lambda: settings.rubric_version)
    model: str = field(default_factory=lambda: settings.model_judge)

    def recompute_aggregate(self) -> float:
        return sum(
            getattr(self, dim) * weight
            for dim, weight in WEIGHTS.items()
        )

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Core evaluator
# ---------------------------------------------------------------------------
def evaluate_transcript(
    messages: list[dict] | None = None,
    transcript: str = "",
    structured_data: dict | None = None,
    extra_context: str = "",
) -> ScoreBreakdown:
    """Score a conversation using the OpenRouter judge.

    Accepts either:
    - messages: list of {role, content} dicts (from chat or call artifact.messages)
    - transcript: raw string (from call artifact.transcript)

    If structured_data is provided (from analysisPlan), it contributes a hard-check
    score blended with the soft LLM judge score.
    """
    if transcript:
        transcript_text = transcript
    elif messages:
        transcript_text = "\n".join(
            f"{m.get('role','?').upper()}: {m.get('message', m.get('content',''))}"
            for m in messages
        )
    else:
        return ScoreBreakdown(failed=True, error="No transcript or messages provided")

    user_content = f"<transcript>\n{transcript_text}\n</transcript>"
    if extra_context:
        user_content += f"\n\n<context>{extra_context}</context>"
    user_content += "\n\nScore this conversation per the rubric."

    try:
        parsed = complete_json(
            system=JUDGE_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
            model=settings.model_judge,
            temperature=0.0,
        )
    except (ValueError, Exception) as e:
        logger.error(f"Judge call failed: {e}")
        return ScoreBreakdown(failed=True, error=str(e))

    dims = list(WEIGHTS.keys())
    missing = [d for d in dims if d not in parsed]
    if missing:
        logger.warning(f"Judge response missing dimensions: {missing}")

    score = ScoreBreakdown(
        task_completion=float(parsed.get("task_completion", 0)),
        turn_efficiency=float(parsed.get("turn_efficiency", 0)),
        graceful_handling=float(parsed.get("graceful_handling", 0)),
        tone_naturalness=float(parsed.get("tone_naturalness", 0)),
        error_recovery=float(parsed.get("error_recovery", 0)),
        aggregate=float(parsed.get("aggregate", 0)),
        reasoning=parsed.get("reasoning", ""),
    )
    # Validate aggregate matches formula (warn if off by > 0.02)
    recomputed = score.recompute_aggregate()
    if abs(recomputed - score.aggregate) > 0.02:
        logger.warning(f"Judge aggregate {score.aggregate:.3f} differs from recomputed {recomputed:.3f}; using recomputed")
        score.aggregate = round(recomputed, 4)

    # Blend with hard checks from analysisPlan structuredData if available
    if structured_data:
        slots = ["patient_name", "appointment_date", "procedure", "contact_info"]
        filled = sum(1 for s in slots if structured_data.get(s, "").strip())
        hard_score = filled / len(slots)
        booked = structured_data.get("appointment_booked", False)
        if not booked:
            hard_score *= 0.5  # penalise if booking never confirmed
        # Blend: 80% soft judge, 20% hard slot check
        blended = round(0.8 * score.aggregate + 0.2 * hard_score, 4)
        logger.info(f"Hard check: slots={filled}/{len(slots)} booked={booked} hard={hard_score:.3f} blended={blended:.3f}")
        score.aggregate = blended

    return score


# ---------------------------------------------------------------------------
# Judge variance check (P4.4)
# ---------------------------------------------------------------------------
def judge_check(fixture_path: Path) -> None:
    """Load a transcript fixture and score it twice. Fails if variance is high."""
    if not fixture_path.exists():
        logger.error(f"Fixture not found: {fixture_path}")
        sys.exit(1)

    data = json.loads(fixture_path.read_text())
    messages = data.get("messages", data)  # handle both shapes

    logger.info(f"Running judge-check on {fixture_path.name} (2 runs)...")
    results = []
    for i in range(2):
        score = evaluate_transcript(messages)
        results.append(score)
        logger.info(f"  run {i+1}: aggregate={score.aggregate:.4f} reasoning={score.reasoning!r}")

    delta = abs(results[0].aggregate - results[1].aggregate)
    threshold = settings.judge_variance_threshold
    logger.info(f"Variance (aggregate): {delta:.4f} (threshold={threshold})")

    if delta > threshold:
        logger.error(f"FAIL: judge variance {delta:.4f} exceeds threshold {threshold}")
        sys.exit(1)
    else:
        logger.info("PASS: judge variance within threshold")
