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


# Pages that label themselves adult (the RTA standard, or an explicit "adult" rating meta tag).
ADULT_RATING = re.compile(r"rta-5042-1996-1400-1577-rta|\badult\b|\bmature\b|\b18\+|\bexplicit\b")
# Explicit terms counted by how often they appear, not just whether they do.
EXPLICIT_TERMS = re.compile(r"\bporn\w*|\bxxx\b|\bhentai\b|\bcum ?shots?\b|\bblowjobs?\b|\bcreampie\b|\bnsfw\b")
DENSITY_MIN_HITS = 8  # a news article mentions these a few times; an adult site saturates the page
DENSITY_PER_1000_WORDS = 5


def score_page(url: str, title: str, text: str, rating: str = "") -> Result:
    haystack = f"{url}\n{title}\n{text}".lower()
    res = Result()
    host = urlsplit(url).hostname or ""
    if BAD_HOST.search(host):
        res.score = 100
        res.reasons.append(f"adult site name: {host}")
        return res
    if ADULT_RATING.search(rating.lower()):
        res.score = 100
        res.reasons.append(f"page is labeled adult: {rating[:60]}")
        return res
    hits = len(EXPLICIT_TERMS.findall(haystack))
    words = max(len(haystack.split()), 1)
    if hits >= DENSITY_MIN_HITS and hits / words * 1000 >= DENSITY_PER_1000_WORDS:
        res.score += 10
        res.reasons.append(f"explicit terms: {hits} in {words} words")
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
