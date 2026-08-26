# Flaky Test Diagnoser

A closed-loop CLI agent that repeatedly runs a flaky Python test, analyzes the
evidence, proposes a fix, applies it safely to a copy, and verifies the result
with another independent run series.

The implementation is being built incrementally. See the package modules for
the planned responsibilities.
