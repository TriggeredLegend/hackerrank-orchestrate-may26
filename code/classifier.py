"""
Rule-based classifier for ticket triage:
  - request_type  : product_issue | feature_request | bug | invalid
  - should_escalate: True/False + reason
  - product_area  : best-fit support category derived from retrieved docs
"""

import re
from typing import List, Dict, Tuple

# ---------------------------------------------------------------------------
# Keyword sets (lowercased)
# ---------------------------------------------------------------------------

_BUG_KEYWORDS = {
    "not working", "broken", "bug", "error", "crash", "down", "outage",
    "failing", "fails", "failed", "stopped working", "does not work",
    "doesn't work", "cant access", "cannot access", "can't access",
    "inaccessible", "404", "500", "timeout", "freezing", "frozen",
    "stuck", "glitch", "problem with", "issue with", "not loading",
    "not responding", "no response", "connectivity", "connection",
}

_FEATURE_KEYWORDS = {
    "feature request", "could you add", "please add",
    "would be great if", "suggestion", "wishlist",
    "can you implement", "add support for",
    "request a feature", "new feature",
}

_INVALID_KEYWORDS = {
    # clearly off-topic or malicious (use full phrases to avoid partial matches)
    "delete all files", "rm -rf", "format disk", "bypass security",
    "show me the system prompt", "ignore previous instructions",
    "forget instructions", "show internal rules",
    "affiche toutes les règles internes",
    "logique exacte", "documents récupérés",
    # utterly off-topic
    "iron man",
}

# Patterns that are checked as whole-word / phrase matches (not substrings)
_INVALID_PATTERNS = [
    re.compile(r"\bactor\s+in\b", re.I),          # "actor in Iron Man"
    re.compile(r"\bwhat\s+movie\b", re.I),
    re.compile(r"^thank\s+you\b", re.I),           # bare "thank you" as entire message
    re.compile(r"^thanks\b", re.I),
    re.compile(r"^(hi|hello|hey)\s*$", re.I),      # empty greeting
    re.compile(r"\bweather\s+forecast\b", re.I),
    re.compile(r"\brecipe\s+for\b", re.I),
]

_INVALID_TOPICS = {
    "actor in iron man", "movie", "recipe", "weather",
    "thank you", "thanks", "hello", "hi there only",
}

# Issues that MUST be escalated (high-risk / sensitive)
_ESCALATE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # Billing / payments / refunds
    (re.compile(r"\brefund\b", re.I), "refund request requires human review"),
    (re.compile(r"\bpayment\b.*\border\b|\border\b.*\bpayment\b", re.I), "payment/order issue requires human review"),
    (re.compile(r"\bbilling\b", re.I), "billing issue requires human review"),
    (re.compile(r"\bsubscription\b.*(pause|cancel|stop|end)\b|(pause|cancel|stop|end).*\bsubscription\b", re.I), "subscription change requires human review"),
    (re.compile(r"\bcharge\b.*\bdispute\b|\bdispute\b.*\bcharge\b", re.I), "charge dispute requires human review"),
    (re.compile(r"\bdispute\b", re.I), "dispute requires human review"),

    # Fraud / security
    (re.compile(r"\bidentity theft\b|\bidentity has been stolen\b", re.I), "identity theft is a critical security issue"),
    (re.compile(r"\bfraud\b", re.I), "fraud-related issue requires human review"),
    (re.compile(r"\b(account|identity)\b.{0,20}\bstolen\b|\bstolen\b.{0,20}\b(account|identity)\b", re.I), "stolen account/identity requires immediate human attention"),
    (re.compile(r"\bsecurity vulnerability\b|\bbug bounty\b", re.I), "security vulnerability report requires specialist review"),
    (re.compile(r"\bhacked\b|\bcompromised\b", re.I), "potential security compromise requires human review"),

    # Account access / permissions
    (re.compile(r"\brestore.{0,30}(access|account)\b", re.I), "account access restoration requires human review"),
    (re.compile(r"\b(access|account).{0,30}(restore|reinstate|recover)\b", re.I), "account access recovery requires human review"),
    (re.compile(r"\blocke?d\b.{0,40}\b(account|workspace)\b|\b(account|workspace)\b.{0,40}\blocke?d\b", re.I), "locked account/workspace requires human review"),
    (re.compile(r"\bblocked\b.{0,20}\bcard\b|\bcard\b.{0,20}\bblocked\b", re.I), "blocked card requires human review"),

    # Score / grade manipulation
    (re.compile(r"\b(increase|change|modify|adjust|fix).{0,30}\b(score|grade|result)\b", re.I), "score/grade modification not possible; human review required"),
    (re.compile(r"\bscore dispute\b|\bgrading dispute\b", re.I), "score dispute requires human review"),

    # Rescheduling assessments (candidate cannot reschedule; needs company/HR)
    (re.compile(r"\breschedul\w+.{0,80}(assessment|test)\b|\b(assessment|test).{0,40}reschedul\w+\b", re.I), "rescheduling assessment requires company/HR decision"),
    (re.compile(r"\breschedul\w+.{0,30}(interview)\b", re.I), "rescheduling interview - check if agent can handle or escalate"),

    # Widespread outages
    (re.compile(r"\b(all|every|none).{0,30}(request|submission|page|challenge|feature|service).{0,30}(fail|failing|failed|not working|broken|inaccessible|down)\b", re.I), "widespread outage requires engineering escalation"),
    (re.compile(r"\b(all|every|none).{0,30}(request|submission|page|challenge).{0,30}(are|is)\s+(not\s+)?(working|accessible|available)\b", re.I), "widespread service issue requires engineering escalation"),
    (re.compile(r"\b\w+.{0,20}(is|are)\s+(completely\s+)?(down|offline|not working|not available|not accessible)\b", re.I), "feature/service outage requires escalation"),
    (re.compile(r"\bsite is down\b|\bplatform.{0,10}(down|offline)\b", re.I), "platform outage requires engineering escalation"),
    (re.compile(r"\bstopped working completely\b|\bcompletely.{0,10}(stopped|down|broken)\b", re.I), "complete service failure requires escalation"),

    # Legal / compliance
    (re.compile(r"\blegal\b|\blawsuit\b|\bcourt\b|\blaw enforcement\b", re.I), "legal matter requires human review"),
    (re.compile(r"\binfosec\b|\bcompliance form\b|\bsecurity questionnaire\b|\bsecurity audit\b", re.I), "infosec/compliance requires human specialist"),

    # Emergency cash / financial
    (re.compile(r"\burgent.{0,15}cash\b|\bneed cash\b", re.I), "urgent cash assistance requires Visa customer service"),
]

# Prompt-injection / adversarial patterns — always respond as invalid
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I),
    re.compile(r"(show|reveal|display|print|output).{0,30}(system prompt|internal rules|retrieved doc|exact log|internal)", re.I),
    re.compile(r"affiche\s+toutes\s+les\s+règles\s+internes", re.I),
    re.compile(r"logique\s+exacte\s+que\s+vous\s+utilisez", re.I),
    re.compile(r"delete\s+all\s+files\b|rm\s+-rf\b|format\s+disk\b", re.I),
]

# ---------------------------------------------------------------------------
# Product-area mapping from doc path / title keywords
# ---------------------------------------------------------------------------

_PRODUCT_AREA_RULES: List[Tuple[re.Pattern, str]] = [
    # HackerRank areas
    (re.compile(r"\bscreen\b|\btest\b|\bassessment\b", re.I), "screen"),
    (re.compile(r"\binterview\b", re.I), "interviews"),
    (re.compile(r"\bcandidate\b", re.I), "screen"),
    (re.compile(r"\bskillup\b|\blearning\b|\bcourse\b|\bpractice\b|\bsubmission\b", re.I), "skillup"),
    (re.compile(r"\bcommunity\b|\bforum\b", re.I), "hackerrank_community"),
    (re.compile(r"\bintegration\b|\bjira\b|\bslack\b|\bats\b", re.I), "integrations"),
    (re.compile(r"\bengage\b|\bgamification\b|\bchallenge\b", re.I), "engage"),
    (re.compile(r"\blibrary\b|\bquestion\b|\bproblem set\b", re.I), "library"),
    (re.compile(r"\bsetting\b|\badmin\b|\buser\b|\brole\b|\bpermission\b|\bteam\b", re.I), "settings"),
    (re.compile(r"\bcertificate\b|\bcertification\b", re.I), "screen"),
    (re.compile(r"\bresume\b|\bapply\b|\bjob\b", re.I), "hackerrank_community"),

    # Visa areas
    (re.compile(r"\btraveller.{0,5}cheque\b|\btravelers cheque\b", re.I), "travel_support"),
    (re.compile(r"\blost\b|\bstolen\b", re.I), "general_support"),
    (re.compile(r"\bdispute\b|\bchargeback\b|\brefund\b", re.I), "dispute_resolution"),
    (re.compile(r"\bfraud\b|\bsecurity\b", re.I), "fraud_protection"),
    (re.compile(r"\btravel\b|\bcurrency\b|\bexchange\b", re.I), "travel_support"),
    (re.compile(r"\bminimum.{0,10}spend\b|\bsurcharge\b|\bcheckout fee\b", re.I), "visa_rules"),
    (re.compile(r"\bidentity theft\b", re.I), "fraud_protection"),
    (re.compile(r"\bcard\b|\bpin\b|\bpayment\b", re.I), "general_support"),

    # Claude areas
    (re.compile(r"\bprivacy\b|\bdelete.{0,15}conversation\b|\bdata\b", re.I), "privacy"),
    (re.compile(r"\bapi\b|\bbedrock\b|\bconsole\b", re.I), "claude_api"),
    (re.compile(r"\bteam\b|\benterprise\b|\bworkspace\b|\bseat\b|\badmin\b", re.I), "team_and_enterprise"),
    (re.compile(r"\bpro\b|\bmax\b|\bplan\b|\bsubscription\b", re.I), "pro_and_max_plans"),
    (re.compile(r"\bbug bounty\b|\bvulnerability\b", re.I), "safeguards"),
    (re.compile(r"\blti\b|\beducation\b|\bstudent\b|\bprofessor\b", re.I), "claude_for_education"),
    (re.compile(r"\bcrawl\b|\bbot\b|\bscrape\b", re.I), "privacy_and_legal"),
    (re.compile(r"\bidentity\b|\bsso\b|\bscim\b|\bsaml\b", re.I), "identity_management"),
    (re.compile(r"\bdesktop\b|\bmobile\b|\bapp\b", re.I), "claude_desktop"),
    (re.compile(r"\bconversation\b|\bchat\b|\bmessage\b", re.I), "conversation_management"),
]

_GENERIC_AREAS = {
    "HackerRank": "general_support",
    "Claude": "general_support",
    "Visa": "general_support",
    "None": "general_support",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_injection_attempt(issue: str, subject: str) -> bool:
    text = f"{issue} {subject}"
    return any(p.search(text) for p in _INJECTION_PATTERNS)


def classify_request_type(issue: str, subject: str) -> str:
    text = f"{issue} {subject}".lower()
    combined_raw = f"{issue} {subject}"

    # Check invalid first (covers injection and clearly off-topic)
    for kw in _INVALID_KEYWORDS:
        if kw in text:
            return "invalid"
    for pat in _INVALID_PATTERNS:
        if pat.search(combined_raw):
            return "invalid"

    # Check feature request
    for kw in _FEATURE_KEYWORDS:
        if kw in text:
            return "feature_request"

    # Check bug
    for kw in _BUG_KEYWORDS:
        if kw in text:
            return "bug"

    return "product_issue"


def should_escalate(issue: str, subject: str, company: str) -> Tuple[bool, str]:
    """
    Returns (True, reason) if the ticket should be escalated, else (False, "").
    """
    text = f"{issue} {subject}"

    # Injection attempts → reply as invalid (not escalate)
    if is_injection_attempt(issue, subject):
        return False, ""

    for pattern, reason in _ESCALATE_PATTERNS:
        if pattern.search(text):
            return True, reason

    return False, ""


def classify_product_area(
    issue: str, subject: str, company: str, retrieved_docs: List[Dict]
) -> str:
    """
    Determine the best-fit product area using:
    1. Keywords in issue/subject
    2. Company label of the top retrieved document
    """
    combined = f"{issue} {subject}"

    for pattern, area in _PRODUCT_AREA_RULES:
        if pattern.search(combined):
            return area

    # Fall back to doc-derived area
    if retrieved_docs:
        top_doc = retrieved_docs[0]
        # try matching doc path segments
        doc_path = top_doc.get("path", "")
        parts = re.split(r"[/\\]", doc_path)
        if len(parts) > 1:
            return parts[-2].replace("-", "_").replace(" ", "_").lower()

    return _GENERIC_AREAS.get(company, "general_support")
