"""
BM25-based corpus retriever over the local support documentation.

Loads all .md files from the data/ directory, strips YAML front-matter,
and builds a BM25 index for fast, offline retrieval.
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Tuple

from rank_bm25 import BM25Okapi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1)


def _tokenize(text: str) -> List[str]:
    text = text.lower()
    tokens = re.findall(r"[a-z0-9']+", text)
    return tokens


# Minimum BM25 score for company-specific filtering to be trusted.
# Below this threshold the corpus-wide ranking is used instead.
_MIN_COMPANY_SCORE_THRESHOLD = 0.5


def _extract_metadata(text: str, path: str) -> Dict:
    """Pull title and source_url from YAML front-matter if present."""
    meta = {"title": "", "source_url": "", "path": path}
    m = _FRONTMATTER_RE.match(text)
    if m:
        block = m.group()
        for key in ("title", "source_url"):
            km = re.search(rf'^{key}:\s*"?(.*?)"?\s*$', block, re.MULTILINE)
            if km:
                meta[key] = km.group(1).strip().strip('"')
    return meta


# ---------------------------------------------------------------------------
# Document loader
# ---------------------------------------------------------------------------

def load_corpus(data_dir: str) -> List[Dict]:
    """
    Walk *data_dir* recursively and return one dict per .md file.
    Each dict has keys: path, title, source_url, company, content, tokens.
    """
    docs = []
    data_path = Path(data_dir)

    for md_file in sorted(data_path.rglob("*.md")):
        rel = str(md_file.relative_to(data_path))
        try:
            raw = md_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        meta = _extract_metadata(raw, rel)
        content = _strip_frontmatter(raw).strip()
        if not content:
            continue

        # infer company from top-level folder
        parts = rel.split(os.sep)
        company = parts[0].lower() if parts else "unknown"
        company_map = {
            "hackerrank": "HackerRank",
            "claude": "Claude",
            "visa": "Visa",
        }
        meta["company"] = company_map.get(company, company)
        meta["content"] = content
        meta["tokens"] = _tokenize(content + " " + meta["title"])
        docs.append(meta)

    return docs


# ---------------------------------------------------------------------------
# BM25 Retriever
# ---------------------------------------------------------------------------

class Retriever:
    """Offline BM25 retriever over the support corpus."""

    def __init__(self, data_dir: str):
        self.docs = load_corpus(data_dir)
        if not self.docs:
            raise RuntimeError(f"No documents found in {data_dir}")
        corpus_tokens = [d["tokens"] for d in self.docs]
        self.bm25 = BM25Okapi(corpus_tokens)

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        company_filter: str | None = None,
    ) -> List[Dict]:
        """
        Return up to *top_k* documents most relevant to *query*.

        If *company_filter* is provided (e.g. 'HackerRank'), a two-pass
        strategy is used: first try to find docs from that company, then
        fall back to corpus-wide if the top company-specific score is low.
        """
        q_tokens = _tokenize(query)
        scores = self.bm25.get_scores(q_tokens)

        # Build (score, doc) pairs
        ranked = sorted(
            zip(scores, self.docs), key=lambda x: x[0], reverse=True
        )

        if company_filter:
            company_hits = [
                (s, d) for s, d in ranked if d["company"] == company_filter
            ]
            # Use company-specific if top score is meaningful
            if company_hits and company_hits[0][0] > _MIN_COMPANY_SCORE_THRESHOLD:
                return [d for _, d in company_hits[:top_k]]

        # Fall back to global ranking
        return [d for _, d in ranked[:top_k]]

    def extract_best_paragraphs(
        self, doc_content: str, query: str, n: int = 3, min_len: int = 60
    ) -> List[str]:
        """
        Split a document into paragraphs and return the top-n most relevant
        to *query* by BM25 score.
        """
        paragraphs = [
            p.strip()
            for p in re.split(r"\n{2,}", doc_content)
            if len(p.strip()) >= min_len
        ]
        if not paragraphs:
            return [doc_content[:500]]

        # Small inline BM25 over paragraphs
        para_tokens = [_tokenize(p) for p in paragraphs]
        try:
            bm = BM25Okapi(para_tokens)
            q_tokens = _tokenize(query)
            scores = bm.get_scores(q_tokens)
            ranked = sorted(zip(scores, paragraphs), key=lambda x: x[0], reverse=True)
            return [p for _, p in ranked[:n]]
        except Exception:
            return paragraphs[:n]
