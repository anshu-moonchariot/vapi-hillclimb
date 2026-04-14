"""Central configuration: loads .env, exposes Settings object.

No magic numbers in downstream modules — import Settings only.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from repo root (two levels up from this file)
_ROOT = Path(__file__).parent.parent.parent
load_dotenv(_ROOT / ".env")


class Settings:
    # Paths
    root: Path = _ROOT
    runs_dir: Path = _ROOT / "runs"
    results_dir: Path = _ROOT / "results"
    prompts_dir: Path = _ROOT / "prompts"
    rubric_path: Path = _ROOT / "src" / "vapi_takehome" / "rubric" / "v1.md"
    baseline_prompt_path: Path = _ROOT / "prompts" / "baseline_system.txt"

    # Vapi
    vapi_api_key: str = os.environ["VAPI_API_KEY"]
    vapi_base_url: str = os.environ.get("VAPI_BASE_URL", "https://api.vapi.ai").rstrip("/")
    voice_enabled: bool = os.environ.get("VOICE_ENABLED", "false").lower() == "true"
    vapi_phone_number_id: str = os.environ.get("VAPI_PHONE_NUMBER_ID", "")
    patient_phone_number_id: str = os.environ.get("PATIENT_PHONE_NUMBER_ID", "")
    test_destination_e164: str = os.environ.get("TEST_DESTINATION_E164", "")

    # OpenRouter
    openrouter_api_key: str = os.environ["OPENROUTER_API_KEY"]
    openrouter_base_url: str = os.environ.get(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    ).rstrip("/")
    _or_default: str = os.environ.get("OPENROUTER_MODEL_DEFAULT", "openai/gpt-4o")
    model_caller: str = os.environ.get("OPENROUTER_MODEL_CALLER", "") or _or_default
    model_judge: str = os.environ.get("OPENROUTER_MODEL_JUDGE", "") or _or_default
    model_mutator: str = os.environ.get("OPENROUTER_MODEL_MUTATOR", "") or _or_default

    # Optimization hyperparameters
    n_rollouts: int = int(os.environ.get("N", 5))
    k_mutations: int = int(os.environ.get("K", 3))
    t_iterations: int = int(os.environ.get("T", 5))
    delta: float = float(os.environ.get("DELTA", 0.03))
    max_turns: int = int(os.environ.get("MAX_TURNS", 12))
    seed: int = int(os.environ.get("SEED", 42))

    # Evaluation
    judge_variance_threshold: float = float(os.environ.get("JUDGE_VARIANCE_THRESHOLD", 0.1))
    rubric_version: str = "v1"

    # Rubric weights (must sum to 1.0)
    rubric_weights: dict = {
        "task_completion": 0.35,
        "turn_efficiency": 0.20,
        "graceful_handling": 0.20,
        "tone_naturalness": 0.15,
        "error_recovery": 0.10,
    }

    # HTTP timeouts
    http_connect_timeout: float = 10.0
    http_read_timeout: float = 120.0

    # Max prompt length (chars) for mutation validation
    max_prompt_chars: int = 3000


settings = Settings()
