"""Optimization engine: baseline measurement + hill-climbing loop + reporting.

Public entrypoints (called by cli.py):
  run_baseline(n_override)
  run_optimize(n_override, k_override, t_override, delta_override)
  run_final_eval(run_id)
  print_report(run_id)
"""

import csv
import hashlib
import json
import random
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from vapi_takehome.config import settings
from vapi_takehome.evaluation import ScoreBreakdown, evaluate_transcript
from vapi_takehome.harness import RolloutResult, all_persona_ids, run_call_rollout, run_chat_rollout
from vapi_takehome.logging_config import get_logger
from vapi_takehome.openrouter import complete_json
from vapi_takehome.vapi_client import RECEPTIONIST_FIRST_MESSAGE, create_assistant, update_assistant

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:12]


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def _make_run_dir(run_id: str) -> Path:
    d = settings.runs_dir / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "rollouts").mkdir(exist_ok=True)
    (d / "iterations").mkdir(exist_ok=True)
    return d


def _persona_schedule(n: int) -> list[str]:
    """Round-robin persona IDs to fill n slots."""
    ids = all_persona_ids()
    random.seed(settings.seed)
    schedule = []
    for i in range(n):
        schedule.append(ids[i % len(ids)])
    return schedule


def _run_rollouts(
    client: httpx.Client,
    assistant_id: str,
    persona_schedule: list[str],
    run_dir: Path,
    label: str,
    run_id: str,
    mode: str = "voice",
) -> tuple[list[RolloutResult], list[ScoreBreakdown]]:
    """Run all rollouts for one prompt variant; evaluate each. Returns (rollouts, scores).

    mode: "voice" uses POST /call (real phone calls); "chat" uses POST /chat (no PSTN).
    """
    rollouts: list[RolloutResult] = []
    scores: list[ScoreBreakdown] = []

    for i, persona_id in enumerate(persona_schedule):
        log = get_logger(__name__, run_id)
        log.info(f"[{label}] rollout {i+1}/{len(persona_schedule)} persona={persona_id} mode={mode}")
        if mode == "chat":
            rollout = run_chat_rollout(client, assistant_id, persona_id, run_id=run_id)
        else:
            rollout = run_call_rollout(client, assistant_id, persona_id, run_id=run_id)
        rollouts.append(rollout)

        if rollout.failed:
            score = ScoreBreakdown(failed=True, error=rollout.error)
        else:
            score = evaluate_transcript(
                messages=rollout.messages or None,
                transcript=rollout.transcript,
                structured_data=rollout.structured_data or None,
            )

        scores.append(score)

        # Save rollout
        rollout_file = run_dir / "rollouts" / f"{label}_{i+1:03d}.json"
        rollout_file.write_text(json.dumps({
            "rollout": rollout.to_dict(),
            "score": score.to_dict(),
        }, indent=2))
        log.info(f"  → aggregate={score.aggregate:.3f} failed={score.failed}")

    return rollouts, scores


def _mean_scores(scores: list[ScoreBreakdown]) -> dict:
    valid = [s for s in scores if not s.failed]
    if not valid:
        return {"aggregate": 0.0, "n_valid": 0, "n_failed": len(scores)}
    dims = list(settings.rubric_weights.keys())
    result = {d: round(sum(getattr(s, d) for s in valid) / len(valid), 4) for d in dims}
    result["aggregate"] = round(sum(s.aggregate for s in valid) / len(valid), 4)
    result["aggregate_std"] = round(
        (sum((s.aggregate - result["aggregate"]) ** 2 for s in valid) / len(valid)) ** 0.5, 4
    )
    result["n_valid"] = len(valid)
    result["n_failed"] = len(scores) - len(valid)
    return result


# ---------------------------------------------------------------------------
# Mutator (P6.2)
# ---------------------------------------------------------------------------

MUTATOR_SYSTEM = """\
You are an expert at improving AI assistant system prompts for a dental office scheduling bot.

You will receive:
1. The CURRENT system prompt
2. The EVALUATION RUBRIC dimensions
3. SHORT EXCERPTS from the lowest-scoring conversations

Your task: produce exactly {k} improved system prompts as a JSON object:
{{
  "candidates": ["<full prompt 1>", "<full prompt 2>", ...]
}}

Rules for each candidate prompt:
- Must be a COMPLETE system prompt (include all necessary instructions)
- Must keep the dental office receptionist role
- Maximum {max_chars} characters
- Fix ONE specific weakness per candidate (don't try to fix everything at once)
- Each candidate should address a DIFFERENT weakness

Weaknesses to address (from rubric + failure examples below):
{failure_summary}
"""


def _build_failure_summary(scores: list[ScoreBreakdown], rollouts: list[RolloutResult]) -> str:
    """Summarize worst-performing rollouts for the mutator."""
    if not scores:
        return "No failure data available."
    paired = sorted(
        [(s, r) for s, r in zip(scores, rollouts) if not s.failed],
        key=lambda x: x[0].aggregate,
    )
    lines = []
    for score, rollout in paired[:2]:
        excerpt = "\n".join(
            f"{m['role'].upper()}: {m['content']}"
            for m in rollout.messages[-6:]  # last 3 turns
        )
        lines.append(
            f"Score: {score.aggregate:.2f} | Reasoning: {score.reasoning}\n"
            f"Conversation excerpt:\n{excerpt}\n"
        )
    return "\n---\n".join(lines) if lines else "No valid rollout excerpts."


def generate_mutations(
    current_prompt: str,
    scores: list[ScoreBreakdown],
    rollouts: list[RolloutResult],
    k: int,
) -> list[str]:
    """Ask OpenRouter to produce k improved prompt candidates."""
    rubric_summary = "\n".join(
        f"- {dim} (weight {w:.0%})" for dim, w in settings.rubric_weights.items()
    )
    failure_summary = _build_failure_summary(scores, rollouts)

    system = MUTATOR_SYSTEM.format(
        k=k,
        max_chars=settings.max_prompt_chars,
        failure_summary=failure_summary,
    )
    user_content = (
        f"CURRENT SYSTEM PROMPT:\n{current_prompt}\n\n"
        f"RUBRIC DIMENSIONS:\n{rubric_summary}\n\n"
        f"Produce {k} improved candidates."
    )

    try:
        parsed = complete_json(
            system=system,
            messages=[{"role": "user", "content": user_content}],
            model=settings.model_mutator,
            temperature=0.7,
        )
    except ValueError as e:
        logger.error(f"Mutator JSON parse failed: {e}")
        return []

    candidates = parsed.get("candidates", [])
    if not isinstance(candidates, list):
        logger.error(f"Mutator returned non-list candidates: {type(candidates)}")
        return []

    valid = []
    for c in candidates:
        if not isinstance(c, str) or not c.strip():
            logger.warning("Mutator: dropping empty/non-string candidate")
            continue
        if len(c) > settings.max_prompt_chars:
            logger.warning(f"Mutator: dropping candidate exceeding max_chars ({len(c)} > {settings.max_prompt_chars})")
            continue
        if "dental" not in c.lower() and "receptionist" not in c.lower() and "appointment" not in c.lower():
            logger.warning("Mutator: dropping candidate that lost dental role context")
            continue
        valid.append(c)

    logger.info(f"Mutator produced {len(valid)}/{k} valid candidates")
    return valid[:k]


# ---------------------------------------------------------------------------
# Phase 5: Baseline
# ---------------------------------------------------------------------------

def run_baseline(n_override: Optional[int] = None, mode: str = "voice") -> dict:
    n = n_override or settings.n_rollouts
    run_id = f"baseline_{_new_run_id()}"
    run_dir = _make_run_dir(run_id)
    log = get_logger(__name__, run_id)

    prompt = settings.baseline_prompt_path.read_text()
    prompt_hash = _prompt_hash(prompt)
    log.info(f"Baseline run starting | n={n} | prompt_hash={prompt_hash}")

    persona_schedule = _persona_schedule(n)

    with httpx.Client() as client:
        assistant_data = create_assistant(
            client, f"Baseline-{run_id}", prompt,
            first_message=RECEPTIONIST_FIRST_MESSAGE,
            first_message_mode="assistant-speaks-first",
        )
        assistant_id = assistant_data["id"]

    # Save baseline assistant ID — never overwrite, never patch this one
    (run_dir / "baseline_assistant_id.txt").write_text(assistant_id)
    log.info(f"Baseline assistant created: {assistant_id}")

    with httpx.Client() as client:
        rollouts, scores = _run_rollouts(client, assistant_id, persona_schedule, run_dir, "baseline", run_id, mode=mode)

    summary = _mean_scores(scores)
    summary["run_id"] = run_id
    summary["assistant_id"] = assistant_id
    summary["prompt_hash"] = prompt_hash
    summary["n"] = n
    summary["persona_schedule"] = persona_schedule
    summary["timestamp"] = _now_iso()

    summary_path = run_dir / "baseline_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    agg_std = summary.get('aggregate_std', 0)
    agg_std_str = f"{agg_std:.3f}" if isinstance(agg_std, (int, float)) else str(agg_std)
    log.info(f"Baseline done | mean_aggregate={summary['aggregate']:.3f} ± {agg_std_str}")
    log.info(f"Summary → {summary_path}")

    return summary


# ---------------------------------------------------------------------------
# Phase 6: Optimization loop
# ---------------------------------------------------------------------------

def run_optimize(
    n_override: Optional[int] = None,
    k_override: Optional[int] = None,
    t_override: Optional[int] = None,
    delta_override: Optional[float] = None,
    mode: str = "voice",
) -> dict:
    n = n_override or settings.n_rollouts
    k = k_override or settings.k_mutations
    t = t_override or settings.t_iterations
    delta = delta_override if delta_override is not None else settings.delta

    run_id = f"optimize_{_new_run_id()}"
    run_dir = _make_run_dir(run_id)
    log = get_logger(__name__, run_id)
    log.info(f"Optimization starting | n={n} k={k} T={t} delta={delta}")

    # Load baseline for initial best_score
    baseline_files = sorted(settings.runs_dir.glob("baseline_*/baseline_summary.json"))
    if not baseline_files:
        raise FileNotFoundError("No baseline run found. Run 'baseline' first.")
    baseline_summary = json.loads(baseline_files[-1].read_text())
    best_score = baseline_summary["aggregate"]
    best_prompt = settings.baseline_prompt_path.read_text()
    log.info(f"Starting from baseline score={best_score:.3f}")

    persona_schedule = _persona_schedule(n)

    # Create dedicated optimizer assistant (never share with baseline)
    with httpx.Client() as client:
        opt_data = create_assistant(
            client, f"Optimizer-{run_id}", best_prompt,
            first_message=RECEPTIONIST_FIRST_MESSAGE,
            first_message_mode="assistant-speaks-first",
        )
    optimizer_assistant_id = opt_data["id"]
    (run_dir / "optimizer_assistant_id.txt").write_text(optimizer_assistant_id)
    log.info(f"Optimizer assistant: {optimizer_assistant_id}")

    plateau_count = 0
    best_rollouts: list[RolloutResult] = []
    best_scores_list: list[ScoreBreakdown] = []
    iteration_log = []

    for t_idx in range(1, t + 1):
        log.info(f"=== Iteration {t_idx}/{t} | best_so_far={best_score:.3f} ===")

        # Generate candidate prompts
        candidates = generate_mutations(best_prompt, best_scores_list, best_rollouts, k)
        if not candidates:
            log.warning("No valid candidates from mutator; skipping iteration")
            plateau_count += 1
        else:
            iteration_best_score = -1.0
            iteration_best_prompt = best_prompt
            iteration_best_rollouts: list[RolloutResult] = []
            iteration_best_scores: list[ScoreBreakdown] = []

            for c_idx, candidate in enumerate(candidates):
                c_label = f"iter{t_idx:02d}_cand{c_idx+1}"
                log.info(f"  Candidate {c_idx+1}/{len(candidates)} hash={_prompt_hash(candidate)}")

                # Apply candidate to optimizer assistant
                with httpx.Client() as client:
                    update_assistant(client, optimizer_assistant_id, candidate)
                    time.sleep(1)  # let Vapi propagate the update
                    c_rollouts, c_scores = _run_rollouts(
                        client, optimizer_assistant_id, persona_schedule, run_dir, c_label, run_id, mode=mode
                    )

                c_mean = _mean_scores(c_scores)["aggregate"]
                log.info(f"  Candidate {c_idx+1} mean={c_mean:.3f}")

                if c_mean > iteration_best_score:
                    iteration_best_score = c_mean
                    iteration_best_prompt = candidate
                    iteration_best_rollouts = c_rollouts
                    iteration_best_scores = c_scores

            # Accept/reject
            if iteration_best_score > best_score + delta:
                log.info(f"ACCEPTED: {best_score:.3f} → {iteration_best_score:.3f} (+{iteration_best_score - best_score:.3f})")
                best_score = iteration_best_score
                best_prompt = iteration_best_prompt
                best_rollouts = iteration_best_rollouts
                best_scores_list = iteration_best_scores
                plateau_count = 0
                decision = "accepted"
            else:
                log.info(f"REJECTED: best candidate {iteration_best_score:.3f} did not beat {best_score:.3f} + {delta}")
                plateau_count += 1
                decision = "rejected"

            # Save iteration log
            iter_data = {
                "t": t_idx,
                "decision": decision,
                "best_score_before": best_score if decision == "rejected" else best_score - (iteration_best_score - best_score),
                "iteration_best_score": iteration_best_score,
                "best_score_after": best_score,
                "candidates_tried": len(candidates),
                "best_prompt_hash": _prompt_hash(best_prompt),
                "plateau_count": plateau_count,
            }
            iteration_log.append(iter_data)
            (run_dir / "iterations" / f"{t_idx:02d}.json").write_text(json.dumps(iter_data, indent=2))

            # Save state after each iteration
            state = {
                "run_id": run_id,
                "t": t_idx,
                "best_score": best_score,
                "best_prompt_hash": _prompt_hash(best_prompt),
                "optimizer_assistant_id": optimizer_assistant_id,
                "plateau_count": plateau_count,
                "timestamp": _now_iso(),
            }
            (run_dir / "state.json").write_text(json.dumps(state, indent=2))

        # Stop on plateau
        if plateau_count >= 2:
            log.info(f"Plateau detected ({plateau_count} rounds without improvement). Stopping early.")
            break

    # Save final best prompt
    (run_dir / "final_prompt.txt").write_text(best_prompt)
    summary = {
        "run_id": run_id,
        "optimizer_assistant_id": optimizer_assistant_id,
        "baseline_score": baseline_summary["aggregate"],
        "final_score": best_score,
        "improvement": round(best_score - baseline_summary["aggregate"], 4),
        "iterations_run": t_idx,
        "iteration_log": iteration_log,
        "final_prompt_hash": _prompt_hash(best_prompt),
        "timestamp": _now_iso(),
    }
    (run_dir / "optimization_summary.json").write_text(json.dumps(summary, indent=2))
    log.info(f"Optimization done | final={best_score:.3f} | improvement={summary['improvement']:+.3f}")
    return summary


# ---------------------------------------------------------------------------
# Phase 7: Final eval
# ---------------------------------------------------------------------------

def run_final_eval(run_id: str, mode: str = "chat") -> dict:
    """Re-run N rollouts on the best prompt; append to results/summary.csv."""
    run_dir = settings.runs_dir / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Run dir not found: {run_dir}")

    opt_summary = json.loads((run_dir / "optimization_summary.json").read_text())
    final_prompt = (run_dir / "final_prompt.txt").read_text()
    optimizer_assistant_id = opt_summary["optimizer_assistant_id"]
    log = get_logger(__name__, run_id)

    # Apply final prompt to optimizer assistant
    with httpx.Client() as client:
        update_assistant(client, optimizer_assistant_id, final_prompt)
        time.sleep(1)

    n = settings.n_rollouts
    persona_schedule = _persona_schedule(n)
    final_dir = _make_run_dir(f"{run_id}_final")

    with httpx.Client() as client:
        rollouts, scores = _run_rollouts(client, optimizer_assistant_id, persona_schedule, final_dir, "final", run_id, mode=mode)

    final_summary = _mean_scores(scores)
    final_summary["run_id"] = run_id
    final_summary["prompt_hash"] = _prompt_hash(final_prompt)
    final_summary["timestamp"] = _now_iso()
    (final_dir / "final_summary.json").write_text(json.dumps(final_summary, indent=2))

    # Append to results/summary.csv
    settings.results_dir.mkdir(exist_ok=True)
    csv_path = settings.results_dir / "summary.csv"
    dims = list(settings.rubric_weights.keys())
    header = ["phase", "run_id", "aggregate", "aggregate_std", "n_valid", "n_failed"] + dims
    row_baseline = _load_baseline_row(opt_summary)
    row_final = ["final", run_id,
                 final_summary["aggregate"], final_summary.get("aggregate_std", ""),
                 final_summary["n_valid"], final_summary["n_failed"]
                 ] + [final_summary.get(d, "") for d in dims]

    write_header = not csv_path.exists()
    with open(csv_path, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(header)
        if row_baseline:
            writer.writerow(row_baseline)
        writer.writerow(row_final)

    log.info(f"Final eval: aggregate={final_summary['aggregate']:.3f} | Results → {csv_path}")

    # Qualitative examples
    _write_examples(rollouts, scores, run_id)

    return final_summary


def _load_baseline_row(opt_summary: dict) -> Optional[list]:
    baseline_files = sorted(settings.runs_dir.glob("baseline_*/baseline_summary.json"))
    if not baseline_files:
        return None
    bs = json.loads(baseline_files[-1].read_text())
    dims = list(settings.rubric_weights.keys())
    return ["baseline", bs.get("run_id", ""), bs["aggregate"], bs.get("aggregate_std", ""),
            bs["n_valid"], bs["n_failed"]] + [bs.get(d, "") for d in dims]


def _write_examples(rollouts: list[RolloutResult], scores: list[ScoreBreakdown], run_id: str):
    """Write 2–3 qualitative transcript examples to results/examples.md."""
    settings.results_dir.mkdir(exist_ok=True)
    paired = [(s, r) for s, r in zip(scores, rollouts) if not s.failed]
    paired.sort(key=lambda x: x[0].aggregate, reverse=True)
    examples = paired[:3]

    lines = [f"# Qualitative Examples — Run {run_id}\n"]
    for i, (score, rollout) in enumerate(examples, 1):
        lines.append(f"## Example {i} — Persona: `{rollout.persona_id}` | Score: {score.aggregate:.3f}\n")
        lines.append(f"**Reasoning:** {score.reasoning}\n")
        lines.append("```")
        for m in rollout.messages:
            lines.append(f"{m['role'].upper()}: {m['content']}")
        lines.append("```\n")

    (settings.results_dir / "examples.md").write_text("\n".join(lines))
    logger.info(f"Examples written → {settings.results_dir / 'examples.md'}")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(run_id: str):
    run_dir = settings.runs_dir / run_id
    for fname in ["optimization_summary.json", "baseline_summary.json"]:
        p = run_dir / fname
        if p.exists():
            data = json.loads(p.read_text())
            print(json.dumps(data, indent=2))
            return
    print(f"No summary found in {run_dir}")
