#!/usr/bin/env python3
"""Backward-compatible command-line entry point."""

from k922_ntrip.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
