#!/usr/bin/env python3
"""
main.py — CLI entry point for the Multi-Domain Support Triage Agent.

Usage:
    python main.py [--input PATH] [--output PATH] [--data-dir PATH]

Defaults:
    --input   ../support_tickets/support_tickets.csv
    --output  ../support_tickets/output.csv
    --data-dir ../data

The agent reads each row from the input CSV, runs the triage pipeline,
and writes results to the output CSV.

Mandatory conversation logging is written to:
    $HOME/hackerrank_orchestrate/log.txt  (Linux/macOS)
    %USERPROFILE%\\hackerrank_orchestrate\\log.txt  (Windows)
"""

import argparse
import csv
import os
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# Logging helpers (AGENTS.md §5)
# ---------------------------------------------------------------------------

_LOG_DIR = Path.home() / "hackerrank_orchestrate"
_LOG_FILE = _LOG_DIR / "log.txt"

# Challenge deadline (IST = UTC+5:30)
_IST = timezone(timedelta(hours=5, minutes=30))
_DEADLINE = datetime(2026, 5, 2, 11, 0, 0, tzinfo=_IST)


def _time_remaining() -> str:
    now = datetime.now(tz=_IST)
    delta = _DEADLINE - now
    if delta.total_seconds() <= 0:
        return "0d 0h 0m (deadline passed)"
    total_minutes = int(delta.total_seconds() // 60)
    days = total_minutes // (60 * 24)
    hours = (total_minutes % (60 * 24)) // 60
    minutes = total_minutes % 60
    return f"{days}d {hours}h {minutes}m"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _ensure_log_dir() -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def _append_log(text: str) -> None:
    _ensure_log_dir()
    with _LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(text + "\n")


def _log_session_start(repo_root: str, branch: str = "unknown") -> None:
    entry = (
        f"\n## [{_now_iso()}] SESSION START\n\n"
        f"Agent: github-copilot\n"
        f"Repo Root: {repo_root}\n"
        f"Branch: {branch}\n"
        f"Worktree: main\n"
        f"Parent Agent: none\n"
        f"Language: py\n"
        f"Time Remaining: {_time_remaining()}\n"
    )
    _append_log(entry)


def _log_turn(title: str, prompt: str, summary: str, actions: list, repo_root: str) -> None:
    actions_str = "\n".join(f"* {a}" for a in actions) if actions else "* (none)"
    entry = (
        f"\n## [{_now_iso()}] {title[:80]}\n\n"
        f"User Prompt (verbatim, secrets redacted):\n"
        f"{prompt}\n\n"
        f"Agent Response Summary:\n"
        f"{summary}\n\n"
        f"Actions:\n{actions_str}\n\n"
        f"Context:\n"
        f"tool=github-copilot\n"
        f"branch=unknown\n"
        f"repo_root={repo_root}\n"
        f"worktree=main\n"
        f"parent_agent=none\n"
    )
    _append_log(entry)


# ---------------------------------------------------------------------------
# CSV processing
# ---------------------------------------------------------------------------

def _get_field(row: dict, *keys: str, default: str = "") -> str:
    """Case-insensitive field lookup."""
    for k in keys:
        for rk in row:
            if rk.strip().lower() == k.lower():
                val = row[rk]
                return val.strip() if val else default
    return default


def run_agent(input_path: str, output_path: str, data_dir: str, verbose: bool = True) -> None:
    """Load tickets, run triage, write output CSV."""

    # Import here so path resolution works when running from any directory
    script_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(script_dir))

    from agent import TriageAgent

    if verbose:
        print(f"[triage] Loading corpus from: {data_dir}")

    agent = TriageAgent(data_dir)

    if verbose:
        print(f"[triage] Corpus loaded. Reading tickets from: {input_path}")

    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if verbose:
        print(f"[triage] Processing {len(rows)} tickets ...")

    output_rows = []
    for i, row in enumerate(rows, 1):
        issue = _get_field(row, "Issue", "issue")
        subject = _get_field(row, "Subject", "subject")
        company = _get_field(row, "Company", "company") or "None"

        try:
            result = agent.process_ticket(issue, subject, company)
        except Exception as exc:  # noqa: BLE001
            # Fail-safe: escalate if something goes wrong
            result = {
                "status": "escalated",
                "product_area": "general_support",
                "response": "An internal error occurred. Escalating to human support.",
                "justification": f"Processing error: {exc}",
                "request_type": "product_issue",
            }
            if verbose:
                print(f"  [!] Error on row {i}: {exc}", file=sys.stderr)
                traceback.print_exc()

        output_row = {
            "Issue": issue,
            "Subject": subject,
            "Company": company,
            "status": result["status"],
            "product_area": result["product_area"],
            "response": result["response"],
            "justification": result["justification"],
            "request_type": result["request_type"],
        }
        output_rows.append(output_row)

        if verbose:
            status_icon = "v" if result["status"] == "replied" else "^"
            print(
                f"  [{i:02d}/{len(rows)}] {status_icon} {result['status']:<10} "
                f"{result['request_type']:<16} | {issue[:60]!r}"
            )

    # Write output CSV
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "Issue", "Subject", "Company",
        "status", "product_area", "response", "justification", "request_type",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    if verbose:
        print(f"\n[triage] Done. Results written to: {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_path(p: str, base: Path) -> str:
    """Resolve relative path against base directory."""
    pp = Path(p)
    if not pp.is_absolute():
        pp = base / pp
    return str(pp.resolve())


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    repo_root = str(script_dir.parent)

    # Determine git branch for logging (best-effort)
    try:
        import subprocess
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        branch = "unknown"

    # Log session start (AGENTS.md §5.1)
    _log_session_start(repo_root=repo_root, branch=branch)

    parser = argparse.ArgumentParser(
        description="Multi-Domain Support Triage Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input", "-i",
        default="../support_tickets/support_tickets.csv",
        help="Path to input CSV (default: ../support_tickets/support_tickets.csv)",
    )
    parser.add_argument(
        "--output", "-o",
        default="../support_tickets/output.csv",
        help="Path to output CSV (default: ../support_tickets/output.csv)",
    )
    parser.add_argument(
        "--data-dir", "-d",
        default="../data",
        help="Path to corpus data directory (default: ../data)",
    )
    parser.add_argument(
        "--sample", "-s",
        action="store_true",
        help="Use sample_support_tickets.csv instead of support_tickets.csv",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress output",
    )
    args = parser.parse_args()

    input_path = _resolve_path(args.input, script_dir)
    output_path = _resolve_path(args.output, script_dir)
    data_dir = _resolve_path(args.data_dir, script_dir)

    if args.sample:
        input_path = str(Path(input_path).parent / "sample_support_tickets.csv")

    # Log this run (AGENTS.md §5.2)
    _log_turn(
        title="Run triage agent on support tickets",
        prompt=(
            f"Run triage agent: input={input_path}, output={output_path}, "
            f"data_dir={data_dir}"
        ),
        summary=(
            "Executed the multi-domain support triage agent. "
            f"Reading tickets from '{input_path}', "
            f"writing results to '{output_path}'. "
            f"Using BM25 retriever over corpus at '{data_dir}'."
        ),
        actions=[
            f"read {input_path}",
            f"BM25 retrieval over {data_dir}",
            f"write {output_path}",
        ],
        repo_root=repo_root,
    )

    run_agent(
        input_path=input_path,
        output_path=output_path,
        data_dir=data_dir,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
