"""
Core triage agent.

For each ticket (issue, subject, company) the agent:
  1. Detects injection / adversarial text → invalid reply
  2. Runs escalation policy → escalated if triggered
  3. Retrieves relevant corpus documents (BM25)
  4. Classifies request_type and product_area
  5. Composes a grounded response from corpus snippets
"""

import re
from typing import Dict, List

from retriever import Retriever
from classifier import (
    classify_request_type,
    classify_product_area,
    should_escalate,
    is_injection_attempt,
)

# ---------------------------------------------------------------------------
# Response templates
# ---------------------------------------------------------------------------

_ESCALATE_RESPONSE = (
    "Thank you for reaching out. Your request has been flagged for review by "
    "our support team. A human agent will follow up with you shortly to assist "
    "with your case."
)

_OUT_OF_SCOPE_RESPONSE = (
    "I'm sorry, but this request falls outside the scope of our support domains "
    "(HackerRank, Claude, and Visa). I'm unable to assist with this topic. "
    "Please contact the relevant service provider directly."
)

_INVALID_INJECTION_RESPONSE = (
    "I'm sorry, but I cannot process this request. It appears to contain content "
    "that is outside the scope of our support service or may violate our usage policy."
)

_CORPUS_CITATION_HEADER = "Based on our support documentation:\n\n"

_MAX_RESPONSE_CHARS = 1400
_SNIPPET_MAX_CHARS = 500

# Patterns to filter out low-quality paragraphs
_SKIP_PATTERNS = [
    re.compile(r"!\[.*?\]\(https?://", re.I),          # image links
    re.compile(r"^\s*[-*]\s*\[.*?\]\(https?://", re.I), # nav link bullets
    re.compile(r"^\s*\[.*?\]\(https?://.*?\)\s*$", re.I), # bare URL lines
    re.compile(r"Related Articles", re.I),
    re.compile(r"_Last (updated|modified):", re.I),
    re.compile(r"^#\s+\w+$"),                           # single-word header
]

_MIN_PARA_LEN = 80


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^\)]+\)")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^\)]+\)")
_MD_HEADER_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_BOLD_RE = re.compile(r"\*\*(.*?)\*\*")
_MD_ITALIC_RE = re.compile(r"\*(.*?)\*")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def _clean_markdown(text: str) -> str:
    """Strip heavy markdown so the response reads naturally."""
    text = _MD_IMAGE_RE.sub("", text)          # remove images
    text = _MD_LINK_RE.sub(r"\1", text)        # keep link text
    text = _MD_HEADER_RE.sub("", text)         # remove headers
    text = _MD_BOLD_RE.sub(r"\1", text)        # unwrap bold
    text = _MD_ITALIC_RE.sub(r"\1", text)      # unwrap italic
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


def _is_useful_paragraph(para: str) -> bool:
    """Return False for paragraphs that are navigation, metadata, or images."""
    for pat in _SKIP_PATTERNS:
        if pat.search(para):
            return False
    clean = _clean_markdown(para).strip()
    if len(clean) < _MIN_PARA_LEN:
        return False
    return True


def _truncate(text: str, max_chars: int = _SNIPPET_MAX_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_dot = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
    if last_dot > max_chars // 2:
        return cut[: last_dot + 1]
    return cut.rstrip() + "…"


# ---------------------------------------------------------------------------
# TriageAgent
# ---------------------------------------------------------------------------

class TriageAgent:
    """Multi-domain support triage agent backed by a local BM25 retriever."""

    def __init__(self, data_dir: str):
        self.retriever = Retriever(data_dir)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def process_ticket(
        self, issue: str, subject: str, company: str
    ) -> Dict[str, str]:
        """
        Process one support ticket and return a dict with keys:
          status, product_area, response, justification, request_type
        """
        issue = issue.strip()
        subject = (subject or "").strip()
        company = (company or "None").strip()

        # ------------------------------------------------------------------
        # 1. Guard: prompt injection / adversarial request
        # ------------------------------------------------------------------
        if is_injection_attempt(issue, subject):
            return {
                "status": "replied",
                "product_area": "general_support",
                "response": _INVALID_INJECTION_RESPONSE,
                "justification": (
                    "The request contains adversarial or prompt-injection patterns "
                    "and cannot be processed."
                ),
                "request_type": "invalid",
            }

        # ------------------------------------------------------------------
        # 2. Detect clearly out-of-scope / meaningless content
        # ------------------------------------------------------------------
        request_type = classify_request_type(issue, subject)
        if request_type == "invalid":
            return {
                "status": "replied",
                "product_area": "general_support",
                "response": _OUT_OF_SCOPE_RESPONSE,
                "justification": (
                    "The request is unrelated to our supported domains "
                    "(HackerRank, Claude, Visa) or contains trivial/off-topic content."
                ),
                "request_type": "invalid",
            }

        # ------------------------------------------------------------------
        # 3. Retrieve relevant documents
        # ------------------------------------------------------------------
        company_filter = company if company != "None" else None
        query = f"{issue} {subject}"
        docs = self.retriever.retrieve(query, top_k=5, company_filter=company_filter)

        # ------------------------------------------------------------------
        # 4. Classify product area
        # ------------------------------------------------------------------
        product_area = classify_product_area(issue, subject, company, docs)

        # ------------------------------------------------------------------
        # 5. Escalation decision
        # ------------------------------------------------------------------
        escalate, esc_reason = should_escalate(issue, subject, company)

        # ------------------------------------------------------------------
        # 6. Compose response
        # ------------------------------------------------------------------
        if escalate:
            response = _ESCALATE_RESPONSE
            justification = (
                f"Escalated: {esc_reason}. This type of request requires "
                "direct handling by a human support agent."
            )
            status = "escalated"
        else:
            response = self._compose_response(query, docs)
            justification = self._compose_justification(docs, request_type)
            status = "replied"

        return {
            "status": status,
            "product_area": product_area,
            "response": response,
            "justification": justification,
            "request_type": request_type,
        }

    # ------------------------------------------------------------------
    # Response composition
    # ------------------------------------------------------------------

    def _compose_response(self, query: str, docs: List[Dict]) -> str:
        """
        Build a grounded response from the top retrieved documents.
        Extracts the most relevant paragraphs via paragraph-level BM25,
        filtering out noise (image links, navigation, metadata).
        """
        if not docs:
            return _OUT_OF_SCOPE_RESPONSE

        snippets: List[str] = []
        chars_used = 0
        seen: set = set()

        for doc in docs[:4]:
            paragraphs = self.retriever.extract_best_paragraphs(
                doc["content"], query, n=3
            )
            for para in paragraphs:
                if not _is_useful_paragraph(para):
                    continue
                clean = _clean_markdown(para)
                if not clean or clean in seen:
                    continue
                seen.add(clean)
                snippet = _truncate(clean, _SNIPPET_MAX_CHARS)
                snippets.append(snippet)
                chars_used += len(snippet)
                if chars_used >= _MAX_RESPONSE_CHARS:
                    break
            if chars_used >= _MAX_RESPONSE_CHARS:
                break

        if not snippets:
            # Fallback: use raw beginning of top doc
            top_doc = docs[0]
            fallback = _clean_markdown(top_doc["content"])
            # skip to first substantial paragraph
            for para in fallback.split("\n\n"):
                if len(para.strip()) >= _MIN_PARA_LEN:
                    snippets.append(_truncate(para.strip(), _SNIPPET_MAX_CHARS))
                    break
            if not snippets:
                return _OUT_OF_SCOPE_RESPONSE

        response = _CORPUS_CITATION_HEADER + "\n\n".join(snippets)

        # Cite the top source
        top_doc = docs[0]
        if top_doc.get("source_url"):
            response += f"\n\nSource: {top_doc['source_url']}"
        elif top_doc.get("title"):
            response += f"\n\n(Reference: {top_doc['title']})"

        return response[:_MAX_RESPONSE_CHARS]

    def _compose_justification(self, docs: List[Dict], request_type: str) -> str:
        if not docs:
            return "No relevant documentation found; responded with general guidance."

        top_doc = docs[0]
        title = top_doc.get("title") or top_doc.get("path", "support docs")
        company = top_doc.get("company", "")
        return (
            f"Responded using {company} support documentation "
            f'("{title}"). '
            f"Request classified as {request_type}; no escalation triggers detected."
        )

