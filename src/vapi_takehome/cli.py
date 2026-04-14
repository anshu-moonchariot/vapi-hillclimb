"""CLI entrypoint: python -m vapi_takehome.cli <subcommand>

Subcommands:
  spike        Re-run the Phase 1 spike script
  judge-check  Validate judge variance on a fixture transcript
  baseline     Run N rollouts against the baseline prompt
  optimize     Run the hill-climbing optimization loop
  final-eval   Evaluate best prompt and produce results artifacts
  report       Print a summary of a completed run
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent


def cmd_spike(args):
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "spike_chat.py")],
        check=True,
    )


def cmd_judge_check(args):
    from vapi_takehome.evaluation import judge_check
    judge_check(Path(args.fixture))


def cmd_baseline(args):
    from vapi_takehome.optimizer import run_baseline
    run_baseline(n_override=args.n, mode=args.mode)


def cmd_optimize(args):
    from vapi_takehome.optimizer import run_optimize
    run_optimize(
        n_override=args.n,
        k_override=args.k,
        t_override=args.t,
        delta_override=args.delta,
        mode=args.mode,
    )


def cmd_final_eval(args):
    from vapi_takehome.optimizer import run_final_eval
    run_final_eval(run_id=args.run_id, mode=args.mode)


def cmd_report(args):
    from vapi_takehome.optimizer import print_report
    print_report(run_id=args.run_id)


def main():
    parser = argparse.ArgumentParser(prog="vapi_takehome", description="Vapi agent optimizer")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("spike", help="Re-run Phase 1 spike")

    p_jc = sub.add_parser("judge-check", help="Validate judge variance on transcript fixture")
    p_jc.add_argument(
        "--fixture",
        default=str(ROOT / "runs" / "spike" / "chat_transcript.json"),
        help="Path to transcript JSON file",
    )

    p_bl = sub.add_parser("baseline", help="Run N rollouts against baseline prompt")
    p_bl.add_argument("--n", type=int, default=None, help="Override N rollouts")
    p_bl.add_argument("--mode", choices=["voice", "chat"], default="voice",
                      help="voice=real phone calls, chat=Vapi Chat API (no PSTN)")

    p_opt = sub.add_parser("optimize", help="Run hill-climbing optimization")
    p_opt.add_argument("--n", type=int, default=None)
    p_opt.add_argument("--k", type=int, default=None)
    p_opt.add_argument("--t", type=int, default=None)
    p_opt.add_argument("--delta", type=float, default=None)
    p_opt.add_argument("--mode", choices=["voice", "chat"], default="voice",
                       help="voice=real phone calls, chat=Vapi Chat API (no PSTN)")

    p_fe = sub.add_parser("final-eval", help="Evaluate best prompt; produce results")
    p_fe.add_argument("--run-id", required=True, help="Run ID from optimization run")
    p_fe.add_argument("--mode", choices=["voice", "chat"], default="chat")

    p_rp = sub.add_parser("report", help="Print summary for a run")
    p_rp.add_argument("--run-id", required=True)

    args = parser.parse_args()
    dispatch = {
        "spike": cmd_spike,
        "judge-check": cmd_judge_check,
        "baseline": cmd_baseline,
        "optimize": cmd_optimize,
        "final-eval": cmd_final_eval,
        "report": cmd_report,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
