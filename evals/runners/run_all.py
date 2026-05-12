"""Run both intent and retrieval evals in one pass.

Usage:
    .venv/bin/python -m evals.runners.run_all
    .venv/bin/python -m evals.runners.run_all --no-auto-preload
"""
import sys

from evals.runners import run_intent, run_retrieval
from evals.runners._common import parse_common_args


def main():
    args = parse_common_args(sys.argv[1:])

    print("=" * 72)
    print("INTENT EVAL")
    print("=" * 72)
    run_intent.run(**args)

    print("\n" + "=" * 72)
    print("RETRIEVAL EVAL")
    print("=" * 72)
    run_retrieval.run(**args)


if __name__ == "__main__":
    main()
