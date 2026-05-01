# HackerRank Orchestrate

A terminal-based, offline multi-domain support triage agent for the **HackerRank Orchestrate** hackathon (May 1–2, 2026). The agent handles support tickets across three product ecosystems — **HackerRank**, **Claude**, and **Visa** — using only the local support corpus under `data/`.

Read [`problem_statement.md`](./problem_statement.md) for the full task spec and [`evalutation_criteria.md`](./evalutation_criteria.md) for how submissions are scored.

---

## Quick Setup

### Prerequisites

- Python 3.9 or later
- pip

### Install

```bash
git clone https://github.com/TriggeredLegend/hackerrank-orchestrate-may26.git
cd hackerrank-orchestrate-may26
pip install rank-bm25 pandas
```

No API keys or network access are needed — the agent runs entirely offline.

### Run

```bash
cd code

# Process support_tickets/support_tickets.csv → support_tickets/output.csv
python main.py

# Quick validation against sample_support_tickets.csv
python main.py --sample

# Custom paths
python main.py --input ../support_tickets/support_tickets.csv \
               --output ../support_tickets/output.csv \
               --data-dir ../data
```

See [`code/README.md`](./code/README.md) for the full CLI reference.

---

## Approach Overview

### Pipeline

Each ticket passes through four stages in sequence:

```
Issue text + Subject + Company
        │
        ▼
1. Safety Guard       — detect prompt-injection / adversarial text → invalid
        │
        ▼
2. BM25 Retrieval     — rank all 774 corpus docs; return top-5 relevant
        │
        ▼
3. Escalation Policy  — regex rules for billing, fraud, outages, etc. → escalated
        │
        ▼
4. Response Composer  — extract best paragraphs from retrieved docs → replied
```

### Retrieval (`retriever.py`)

All 774 markdown files in `data/` (HackerRank help center, Claude Help Center, Visa support) are loaded at startup, stripped of YAML front-matter, tokenized, and indexed with **BM25Okapi** from the `rank_bm25` library.

- For each ticket the query is `{issue} {subject}`.
- When a `company` label is present, company-filtered results are preferred when the top BM25 score exceeds a confidence threshold; otherwise the corpus-wide ranking is used.
- A second pass of paragraph-level BM25 extracts the most relevant snippets from the top documents, filtering out noise (image links, navigation bullets, metadata lines).

### Classification (`classifier.py`)

Three rule sets run in order:

| Rule set | Method | Output |
|----------|--------|--------|
| **Invalid / injection** | Keyword phrases + regex | `request_type = invalid` |
| **Escalation** | Regex patterns on issue + subject text | `status = escalated` |
| **Request type** | Keyword matching | `product_issue / feature_request / bug` |
| **Product area** | Keyword matching + doc path fallback | e.g. `screen`, `privacy`, `general_support` |

Escalation triggers include: billing/refunds, fraud, identity theft, score modification, security vulnerabilities (bug bounty), account access restoration, subscription changes, widespread platform outages, and legal/infosec compliance requests.

### Response Generation (`agent.py`)

For tickets that pass the escalation check, the agent composes a response by:

1. Extracting up to 3 high-quality paragraphs from the top-retrieved documents.
2. Cleaning markdown (removing images, link syntax, headers).
3. Appending the source URL or document title as a citation.

Escalated tickets receive a standard human-handoff message. Invalid tickets receive a scoped out-of-scope reply.

### Logging (`main.py`)

Every run appends session-start and per-turn entries to `$HOME/hackerrank_orchestrate/log.txt` following the AGENTS.md §5 format.

---

## Repository Layout

```
.
├── AGENTS.md                       # Rules for AI coding tools + transcript logging
├── problem_statement.md            # Full task description and I/O schema
├── evalutation_criteria.md         # Scoring rubric
├── README.md                       # You are here
├── code/                           # Agent implementation
│   ├── main.py                     #   CLI entry point
│   ├── agent.py                    #   Core TriageAgent
│   ├── retriever.py                #   BM25 corpus retriever
│   ├── classifier.py               #   Escalation + classification rules
│   ├── requirements.txt            #   Python dependencies
│   └── README.md                   #   Detailed code docs
├── data/                           # Local-only support corpus (no network needed)
│   ├── hackerrank/                 #   HackerRank help center (markdown)
│   ├── claude/                     #   Claude Help Center export (markdown)
│   └── visa/                       #   Visa consumer + small-business support (markdown)
└── support_tickets/
    ├── sample_support_tickets.csv  # Inputs + expected outputs (for development)
    ├── support_tickets.csv         # Inputs only (run your agent on these)
    └── output.csv                  # Agent predictions (generated by main.py)
```

---

## Output Format

For each input row the agent writes five columns:

| Column | Allowed values |
|--------|---------------|
| `status` | `replied`, `escalated` |
| `product_area` | most relevant support category / domain area |
| `response` | user-facing answer grounded in the provided corpus |
| `justification` | concise explanation of the routing/answering decision |
| `request_type` | `product_issue`, `feature_request`, `bug`, `invalid` |

---

## Contents

1. [Quick Setup](#quick-setup)
2. [Approach Overview](#approach-overview)
3. [Repository Layout](#repository-layout)
4. [Output Format](#output-format)
5. [Chat Transcript Logging](#chat-transcript-logging)
6. [Submission](#submission)
7. [Judge Interview](#judge-interview)
8. [Evaluation Criteria](#evaluation-criteria)

---

## Repository layout

```
.
├── AGENTS.md                       # Rules for AI coding tools + transcript logging
├── problem_statement.md            # Full task description and I/O schema
├── README.md                       # You are here
├── code/                           # ← Build your agent here
│   └── main.py                     #   Entry point (rename/extend as you like)
├── data/                           # Local-only support corpus (no network needed)
│   ├── hackerrank/                 #   HackerRank help center
│   ├── claude/                     #   Claude Help Center export
│   └── visa/                       #   Visa consumer + small-business support
└── support_tickets/
    ├── sample_support_tickets.csv  # Inputs + expected outputs (for development)
    ├── support_tickets.csv         # Inputs only (run your agent on these)
    └── output.csv                  # Write your agent's predictions here
```

---

## What you need to build

A terminal-based agent that, for each row in `support_tickets/support_tickets.csv`, produces:

| Column         | Allowed values                                          |
| -------------- | ------------------------------------------------------- |
| `status`       | `replied`, `escalated`                                  |
| `product_area` | most relevant support category / domain area            |
| `response`     | user-facing answer grounded in the provided corpus      |
| `justification`| concise explanation of the routing/answering decision   |
| `request_type` | `product_issue`, `feature_request`, `bug`, `invalid`    |

Hard requirements (from `problem_statement.md`):

- Must be **terminal-based**.
- Must use **only the provided support corpus** (no live web calls for ground-truth answers).
- Must **escalate** high-risk, sensitive, or unsupported cases instead of guessing.
- Must avoid hallucinated policies or unsupported claims.

Beyond that you are free to bring your own approach — RAG, vector DBs, tool use, structured output, agent frameworks, classical ML, or anything else.

---

## Where your code goes

All of your work belongs in [`code/`](./code/). The repo ships with an empty `code/main.py` you can grow into your full agent — add more modules (`agent.py`, `retriever.py`, `classifier.py`, etc.) next to it as needed.

Conventions:

- Put a **README inside `code/`** describing how to install dependencies and run your agent.
- Read secrets **from environment variables only** (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …). Copy `.env.example` → `.env` (already gitignored) if you keep one. **Never hardcode keys.**
- Be **deterministic** where possible. Seed any random sampling.
- Write responses to `support_tickets/output.csv`.

---

## Quickstart

Clone this repository:

```bash
git clone git@github.com:interviewstreet/hackerrank-orchestrate-may26.git
cd hackerrank-orchestrate-may26
```

You are free to use any language or runtime. We recommend **Python**, **JavaScript**, or **TypeScript**.

---

## Chat transcript logging

This repo ships with an `AGENTS.md` that any modern AI coding tool (Cursor, Claude Code, Codex, Gemini CLI, Copilot, etc.) will read. It instructs the tool to append every conversation turn to a single shared log file:

| Platform       | Path                                              |
| -------------- | ------------------------------------------------- |
| macOS / Linux  | `$HOME/hackerrank_orchestrate/log.txt`            |
| Windows        | `%USERPROFILE%\hackerrank_orchestrate\log.txt`    |

You don't need to do anything to enable it — just use your AI tool normally. You'll upload this `log.txt` as your chat transcript at submission time.

---

## Submission

Submit on the HackerRank Community Platform:
<https://www.hackerrank.com/contests/hackerrank-orchestrate-may26/challenges/support-agent/submission>

You will upload **three** files:

1. **Code zip** — zip your `code/` directory and upload it. Exclude virtualenvs, `node_modules`, build artifacts, the `data/` corpus, and the `support_tickets/` CSVs.
2. **Predictions CSV** — your agent's output for `support_tickets/support_tickets.csv` (i.e. the populated `output.csv`).
3. **Chat transcript** — the `log.txt` from the path in [Chat transcript logging](#chat-transcript-logging).

---

## Judge interview

After a successful submission, your AI Judge interview will happen within a few hours after the hackathon ends. It will stay open for the next 4 hours. 

The AI Judge will have access to your submission and may ask about your approach, decisions, and how you used AI while building your solution. The interview will be 30 minutes long, and keeping your camera on is mandatory.

Results will be announced on May 15, 2026

---

## Evaluation criteria

Submissions are scored across four dimensions: agent design (your `code/`), the AI Judge interview, output accuracy on `support_tickets/output.csv`, and AI fluency from your chat transcript.

See [`evalutation_criteria.md`](./evalutation_criteria.md) for the full rubric.