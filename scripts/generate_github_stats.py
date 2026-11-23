#!/usr/bin/env python3

"""Compatibility entry point: all GitHub profile data uses generate_commit_log."""

from generate_commit_log import main


if __name__ == "__main__":
    raise SystemExit(main())
