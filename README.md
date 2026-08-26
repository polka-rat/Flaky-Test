# Flaky Test Diagnoser

Flaky Test Diagnoser is a closed-loop Python agent for pytest failures that
pass and fail inconsistently without source changes. It collects repeated-run
evidence, diagnoses a likely root cause, patches an isolated workspace, and
verifies whether the proposed fix actually works.

The verification phase is the agentic part: a plausible LLM answer is not a
success. A fix is reported only after a fresh post-fix series reaches a 100%
pass rate.

## How it works

```text
RUN N times -> ANALYZE evidence -> DIAGNOSE -> PATCH isolation area -> VERIFY N times
                                           ^                         |
                                           +----- retry (max 3) -----+
```

- Every test execution is a clean pytest subprocess.
- A clean Git repo uses one disposable Git worktree, reset before each attempt.
- A non-Git or dirty repo uses one safe copied fallback.
- The source repository is never overwritten.
- LLM responses must contain a structured exact replacement before patching.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Offline demo

The included demo contains an intentionally random assertion. It needs no API
key and demonstrates the entire diagnose -> patch -> verify loop.

```powershell
flaky-agent diagnose demo_repo test_flaky_random.py::test_random_value_is_not_a_valid_correctness_signal --mock-llm --runs 20
```

Expected outcome: a mixed pre-fix pass rate, followed by a 100% post-fix pass
rate in an isolated workspace.

## Gemini mode

Set your key in the terminal, never in source code or Git:

```powershell
$env:GEMINI_API_KEY = "your-replacement-key"
flaky-agent diagnose <repo-path> <test-id> --runs 20
```

Gemini mode uses a structured JSON response containing diagnosis type,
confidence, target file/line, rationale, exact original text, and replacement
text. The default model is configurable in `Diagnoser/config.py` or via
`--model`.

## Batch evaluation

Evaluation accepts one JSON file or a directory of JSON case files. Each case
has a name, repository path, and pytest target:

```json
{
  "cases": [
    {
      "name": "example",
      "repo_path": "../path-to-repo",
      "test_id": "tests/test_example.py::test_example"
    }
  ]
}
```

Run the included demo configuration:

```powershell
flaky-agent evaluate evaluation_cases --mock-llm --runs 20
```

The terminal summary includes diagnosis type, confidence, pre-fix and post-fix
pass rates, and whether the fix was verified.

## Testing

```powershell
python -m pytest
```

## Evaluation results

| Case | Diagnosis | Pre-fix | Post-fix | Verified |
| --- | --- | --- | --- | --- |
| Synthetic randomness demo | `random_seed` | Variable | 100% | Yes |

Real OSS cases will be added after selecting reported flaky tests to evaluate.
