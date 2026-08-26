"""Command-line interface for Flaky Test Diagnoser."""

import argparse
from functools import partial
from pathlib import Path

from Diagnoser.agent import run_agent
from Diagnoser.config import DEFAULT_GEMINI_MODEL
from Diagnoser.diagnoser import (
    DiagnosisError,
    build_mock_patch_instruction,
    diagnose_mock,
    diagnose_with_agent,
    patch_instruction_from_diagnosis,
)
from Diagnoser.evaluate import (
    EvaluationConfigError,
    load_evaluation_cases,
    render_summary_table,
    run_evaluation,
)


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser and its supported subcommands."""
    parser = argparse.ArgumentParser(
        prog="flaky-agent",
        description="Diagnose flaky pytest tests with a verified fix loop.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    diagnose_parser = subcommands.add_parser(
        "diagnose", help="run the diagnose, patch, and verify loop for one pytest test"
    )
    diagnose_parser.add_argument("repo_path", help="path to the target Python repository")
    diagnose_parser.add_argument(
        "test_id", help="pytest target, e.g. tests/test_widget.py::test_widget"
    )
    diagnose_parser.add_argument("--runs", type=int, default=20, help="runs per phase")
    diagnose_parser.add_argument(
        "--max-attempts", type=int, default=3, help="maximum diagnosis attempts"
    )
    diagnose_parser.add_argument(
        "--timeout", type=float, default=60.0, help="timeout in seconds for one pytest run"
    )
    diagnose_parser.add_argument(
        "--work-root", help="directory for disposable worktrees or copied fallbacks"
    )
    diagnose_parser.add_argument(
        "--mock-llm",
        action="store_true",
        help="use the offline mock diagnosis; no Gemini key or API call",
    )
    diagnose_parser.add_argument(
        "--model",
        default=DEFAULT_GEMINI_MODEL,
        help=f"Gemini model for real mode (default: {DEFAULT_GEMINI_MODEL})",
    )
    diagnose_parser.set_defaults(handler=_diagnose_command)
    evaluate_parser = subcommands.add_parser(
        "evaluate", help="run the closed loop across JSON-configured test cases"
    )
    evaluate_parser.add_argument("config_path", help="a case JSON file or folder of JSON files")
    _add_common_run_arguments(evaluate_parser)
    evaluate_parser.set_defaults(handler=_evaluate_command)
    return parser


def _add_common_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--runs", type=int, default=20, help="runs per phase")
    parser.add_argument("--max-attempts", type=int, default=3, help="maximum diagnosis attempts")
    parser.add_argument("--timeout", type=float, default=60.0, help="timeout in seconds for one pytest run")
    parser.add_argument("--work-root", help="directory for disposable worktrees or copied fallbacks")
    parser.add_argument("--mock-llm", action="store_true", help="use offline mock diagnosis")
    parser.add_argument("--model", default=DEFAULT_GEMINI_MODEL, help="Gemini model for real mode")


def _diagnose_command(args: argparse.Namespace) -> int:
    repository = Path(args.repo_path).expanduser()
    if args.mock_llm:
        diagnosis_function = diagnose_mock
        patch_provider = lambda diagnosis, _: build_mock_patch_instruction(
            repository, diagnosis
        )
        print("MODE: offline mock diagnosis (no API call).")
    else:
        diagnosis_function = partial(diagnose_with_agent, model=args.model)
        patch_provider = lambda diagnosis, _: patch_instruction_from_diagnosis(diagnosis)
        print(f"MODE: Gemini diagnosis using model {args.model}.")

    result = run_agent(
        repository,
        args.test_id,
        runs=args.runs,
        max_attempts=args.max_attempts,
        timeout_seconds=args.timeout,
        work_root=args.work_root,
        diagnose=diagnosis_function,
        patch_provider=patch_provider,
    )
    post_fix_rate = (
        result.attempts[-1].post_fix_analysis.pass_rate if result.attempts else None
    )
    print("\nSUMMARY")
    print(f"  Workspace mode: {result.workspace_mode}")
    print(f"  Pre-fix pass rate: {result.pre_fix_analysis.pass_rate:.0%}")
    print(
        f"  Post-fix pass rate: {post_fix_rate:.0%}"
        if post_fix_rate is not None
        else "  Post-fix pass rate: n/a"
    )
    print(f"  Verified fixed: {'yes' if result.verified_fixed else 'no'}")
    print(f"  Isolated workspace: {result.work_root}")
    return 0 if result.verified_fixed else 1


def _evaluate_command(args: argparse.Namespace) -> int:
    cases = load_evaluation_cases(args.config_path)
    mode = "offline mock diagnosis" if args.mock_llm else f"Gemini ({args.model})"
    print(f"MODE: {mode}.")
    results = run_evaluation(
        cases, runs=args.runs, max_attempts=args.max_attempts,
        timeout_seconds=args.timeout, work_root=args.work_root,
        mock_llm=args.mock_llm, model=args.model,
    )
    print("\nEVALUATION SUMMARY")
    print(render_summary_table(results))
    return 0 if all(result.verified_fixed for result in results) else 1


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (
        DiagnosisError, EvaluationConfigError, FileNotFoundError, NotADirectoryError,
        RuntimeError, ValueError,
    ) as error:
        parser.error(str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
