"""Command-line interface for Flaky Test Diagnoser."""

import argparse


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level parser; subcommands are added incrementally."""
    return argparse.ArgumentParser(
        prog="flaky-agent",
        description="Diagnose flaky pytest tests with a verified fix loop.",
    )


def main() -> None:
    """Run the CLI."""
    build_parser().print_help()


if __name__ == "__main__":
    main()
