# Support Triage Agent

A terminal-based, offline multi-domain support triage agent for HackerRank, Claude, and Visa support tickets.

## Architecture

```
code/
├── main.py        — CLI entry point (session logging, argument parsing, CSV I/O)
├── agent.py       — Core TriageAgent: orchestrates retrieval → escalation → response
├── retriever.py   — BM25 corpus retriever (rank_bm25) over data/ markdown files
├── classifier.py  — Rule-based escalation, request_type, and product_area classifier
└── README.md      — This file
```

### How it works

1. **Retrieval** (`retriever.py`): All 774 markdown documents from `data/` are loaded at startup, stripped of YAML front-matter, tokenized, and indexed with BM25Okapi. For each ticket, the top-5 most relevant documents are retrieved using the issue + subject as a query. A company filter is applied when the ticket specifies `HackerRank`, `Claude`, or `Visa`.

2. **Classification** (`classifier.py`):
   - **Escalation policy**: Regex-based rules detect billing, fraud, identity theft, score disputes, widespread outages, security vulnerabilities, account access issues, subscription changes, rescheduling requests, infosec compliance forms, and other high-risk patterns. Matched tickets are escalated.
   - **Request type**: Keyword-based classification into `product_issue`, `feature_request`, `bug`, or `invalid`. Injection attempts and clearly off-topic requests are flagged as `invalid`.
   - **Product area**: Keyword matching over issue/subject text, with fallback to the top retrieved document's path.

3. **Response generation** (`agent.py`): For non-escalated tickets, the most relevant paragraphs are extracted from retrieved documents using a second pass of BM25 at paragraph level. Noise (images, navigation links, metadata) is filtered out. The response is grounded in corpus snippets and cites the source document.

4. **Logging** (`main.py`): Every run appends session-start and per-turn entries to `$HOME/hackerrank_orchestrate/log.txt` per the AGENTS.md §5 format.

## Installation

```bash
pip install rank-bm25 pandas
```

No other dependencies beyond the Python standard library.

## Usage

```bash
# Process the main support_tickets.csv (default)
python main.py

# Process the sample tickets for validation
python main.py --sample

# Custom input/output paths
python main.py --input /path/to/tickets.csv --output /path/to/results.csv

# Custom data directory
python main.py --data-dir /path/to/data

# Suppress progress output
python main.py --quiet
```

All paths are resolved relative to the `code/` directory if not absolute.

### Options

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--input` | `-i` | `../support_tickets/support_tickets.csv` | Input CSV file |
| `--output` | `-o` | `../support_tickets/output.csv` | Output CSV file |
| `--data-dir` | `-d` | `../data` | Corpus directory |
| `--sample` | `-s` | off | Use `sample_support_tickets.csv` as input |
| `--quiet` | `-q` | off | Suppress progress output |

## Output format

The output CSV has these columns:

| Column | Values |
|--------|--------|
| `Issue` | Original issue text |
| `Subject` | Original subject |
| `Company` | Original company |
| `status` | `replied` or `escalated` |
| `product_area` | Support category / domain area |
| `response` | Grounded user-facing answer |
| `justification` | Explanation of the triage decision |
| `request_type` | `product_issue`, `feature_request`, `bug`, or `invalid` |

## Escalation policy

The following trigger escalation (human review):
- Billing/payment disputes and refund requests
- Subscription management (pause/cancel) for team accounts
- Charge disputes
- Fraud-related issues
- Stolen accounts or identity theft
- Security vulnerability reports / bug bounties
- Score or grade modification requests
- Rescheduling of assessments (candidate-side)
- Widespread platform outages
- Legal/compliance/infosec questionnaires
- Account access restoration without proper credentials
- Urgent financial assistance (Visa emergency)
- Prompt injection / adversarial requests (returned as `replied, invalid`)

## Determinism

BM25 retrieval is deterministic given the same corpus. No random sampling is used. The code is fully reproducible.

## Secrets

No API keys or external calls are needed. The agent runs entirely offline using the local corpus under `data/`.
