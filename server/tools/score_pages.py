"""Score real pages with Shepherd's scorer and show which layer would catch each.

Run from the server/ folder on a machine that can reach the sites:

    python -m tools.score_pages https://example.com/page saved_page.html ...

Takes URLs or saved .html files (use "Save page as" in the browser after passing any age gate,
which gives the same text the extension sees). Prints scores and counts only, never page text.
"""
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from app import config
from app.scoring import (BAD_HOST, DENSITY_MIN_HITS, DENSITY_PER_1000_WORDS, EXPLICIT_TERMS,
                         ADULT_RATING, score_page, verdict_for)


class Visible(HTMLParser):
    """Roughly what document.body.innerText gives the extension."""

    def __init__(self):
        super().__init__()
        self.skip = 0
        self.title = ""
        self.in_title = False
        self.rating = ""
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript", "template"):
            self.skip += 1
        elif tag == "title":
            self.in_title = True
        elif tag == "meta" and (a.get("name") or "").lower() == "rating":
            self.rating = a.get("content") or ""

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template"):
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip and data.strip():
            self.text.append(data.strip())


def load(src: str) -> tuple[str, str]:
    if Path(src).is_file():
        return "https://saved.example/" + Path(src).name, Path(src).read_text(errors="ignore")
    req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return src, r.read(5_000_000).decode("utf-8", "ignore")


def main(sources: list[str]) -> None:
    for src in sources:
        try:
            url, html = load(src)
        except Exception as e:
            print(f"{src}\n  could not load: {e}\n")
            continue
        p = Visible()
        p.feed(html)
        text = " ".join(p.text)[: config.MAX_TEXT_CHARS]
        hay = f"{url}\n{p.title}\n{text}".lower()
        hits, words = len(EXPLICIT_TERMS.findall(hay)), max(len(hay.split()), 1)
        density = hits / words * 1000
        density_block = hits >= DENSITY_MIN_HITS and density >= DENSITY_PER_1000_WORDS
        # Score with the host neutralised so only content signals count.
        content_only = score_page("https://neutral.example/", p.title, text, p.rating)
        full = score_page(url, p.title, text, p.rating)
        print(src)
        print(f"  words={words}  explicit-term hits={hits}  density={density:.1f}/1000 words "
              f"(needs >= {DENSITY_MIN_HITS} hits and >= {DENSITY_PER_1000_WORDS})")
        print(f"  density rule alone: {'BLOCK' if density_block else 'no block'}")
        print(f"  rating label: {p.rating[:50] or '(none)'}  -> {'adult label' if ADULT_RATING.search(p.rating.lower()) else 'not adult'}")
        print(f"  hostname rule: {'match' if BAD_HOST.search(url.split('/')[2] if '//' in url else '') else 'no match'}")
        print(f"  content-only score={content_only.score} -> {verdict_for(content_only.score, config.WARN_SCORE, config.BLOCK_SCORE)}; "
              f"all layers score={full.score} -> {verdict_for(full.score, config.WARN_SCORE, config.BLOCK_SCORE)}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
