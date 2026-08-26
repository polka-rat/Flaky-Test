"""An intentionally flaky test for demonstrating the closed-loop agent."""

import secrets


def test_random_value_is_not_a_valid_correctness_signal() -> None:
    assert secrets.randbelow(2) == 0
