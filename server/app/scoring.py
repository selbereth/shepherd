"""Local rule-based page scoring. No page content leaves the server."""
import re
from urllib.parse import urlsplit
from dataclasses import dataclass, field

# category -> (weight per distinct hit, patterns). Extend via rules file later.
CATEGORIES: dict[str, tuple[int, list[str]]] = {
    "adult": (3, [r"\bporn\w*", r"\bxxx\b", r"\bnsfw\b", r"\bhentai\b", r"\bnude\w*", r"\berotic\w*"]),
    "gambling": (2, [r"\bcasino\b", r"\bsportsbook\b", r"\bpoker\b", r"\bplace your bets?\b"]),
    "drugs": (2, [r"\bbuy (weed|cocaine|mdma|xanax)\b", r"\bdark ?web market\b"]),
    "violence": (2, [r"\bgore\b", r"\bbeheading\b", r"\bsnuff\b"]),
    "self_harm": (4, [r"\bhow to (kill|hurt) (myself|yourself)\b", r"\bsuicide methods?\b"]),
    "grooming_risk": (3, [r"\bdon'?t tell your (parents|mom|dad)\b", r"\bsend (me )?(pics|photos)\b"]),
}


# Hostnames containing these are blocked outright, even if the domain is not on the ban list.
BAD_HOST = re.compile(
    r"porn|xxx|hentai|xvideos|xnxx|xhamster|redtube|youporn|spankbang|chaturbate|livejasmin|camgirl|onlyfans"
)


@dataclass
class Result:
    score: int = 0
    reasons: list[str] = field(default_factory=list)


def score_page(url: str, title: str, text: str) -> Result:
    haystack = f"{url}\n{title}\n{text}".lower()
    res = Result()
    host = urlsplit(url).hostname or ""
    if BAD_HOST.search(host):
        res.score = 100
        res.reasons.append(f"adult site name: {host}")
        return res
    for cat, (weight, patterns) in CATEGORIES.items():
        hits = {m.group(0) for p in patterns for m in re.finditer(p, haystack)}
        if hits:
            res.score += weight * min(len(hits), 3)
            res.reasons.append(f"{cat}: {', '.join(sorted(hits)[:3])}")
    return res


def verdict_for(score: int, warn: int, block: int) -> str:
    if score >= block:
        return "block"
    if score >= warn:
        return "warn"
    return "allow"
