"""Run the Codex QA Agent and print the spec §12.3 report.

Usage (from the project root)::

    python scripts/run_qa.py
    python scripts/run_qa.py --project-root C:/path/to/Technical_Interviewer

Exit code 0 on PASS, 1 on FAIL.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("USE_TF", "0")  # before any ML import

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.agents.qa_agent import format_report, run_qa  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the QA agent.")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT),
                        help="Project root (default: %(default)s)")
    parser.add_argument("--details", action="store_true",
                        help="Also print the raw details section")
    args = parser.parse_args()

    report = run_qa(args.project_root)
    print(format_report(report))
    if args.details and report.details:
        print("\nDetails:\n" + report.details)
    return 0 if report.status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
