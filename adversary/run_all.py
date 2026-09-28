#!/usr/bin/env python3
"""Run all M1 attack scripts and produce a final report."""
from __future__ import annotations

import sys
import time

# Import all attack modules
import attack_concurrency
import attack_repetition
import attack_input
import attack_state
import attack_auth
import attack_visibility
import attack_export_import
import attack_rounding
import attack_resources
from attack_common import RESULTS, summary


def main():
    print("=" * 60)
    print("M1 ATTACK CAMPAIGN")
    print("=" * 60)

    start = time.monotonic()

    attack_concurrency.attack_concurrency()
    attack_repetition.attack_repetition()
    attack_input.attack_input()
    attack_state.attack_state()
    attack_auth.attack_auth()
    attack_visibility.attack_visibility()
    attack_export_import.attack_export_import()
    attack_rounding.attack_rounding()
    attack_resources.attack_resources()

    elapsed = time.monotonic() - start
    print(f"\nTotal elapsed: {elapsed:.1f}s")

    ok = summary()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
