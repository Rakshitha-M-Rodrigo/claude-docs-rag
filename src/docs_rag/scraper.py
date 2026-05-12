"""Scrape and parse documentation from URLs and files."""
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
    from markdownify import markdownify as md
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


class DocScraper:
    """Scrape documentation from web or local files."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session() if HAS_DEPS else None
        if self.session:
            self.session.headers.update({
                "User-Agent": "Mozilla/5.0 (compatible; DocsBot/1.0)"
            })

    def fetch_url(self, url: str) -> str:
        """Fetch URL and convert to markdown."""
        if not HAS_DEPS:
            raise ImportError("requests, beautifulsoup4, and markdownify required for URL scraping")
        
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Remove script/style tags
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        
        # Try to find main content area. Pick the largest candidate so that
        # pages with small auxiliary `class="..content.."` divs (e.g. php.net's
        # `cmd_content`) don't trick us into extracting a nav blurb.
        candidates = []
        for cand in [
            soup.find("main"),
            soup.find("article"),
            *soup.find_all("div", class_=re.compile("content|main|doc")),
        ]:
            if cand is not None:
                candidates.append(cand)

        body = soup.find("body") or soup
        if candidates:
            best = max(candidates, key=lambda t: len(t.get_text(strip=True)))
            best_len = len(best.get_text(strip=True))
            body_len = len(body.get_text(strip=True))
            # Only use the matched container if it's both reasonably large AND
            # captures a meaningful share of the body text. PHP's manual, for
            # example, has many small <div class="example-contents"> code blocks
            # that match the regex but cover <5% of the actual content.
            if best_len >= 500 and best_len * 4 >= body_len:
                html = str(best)
            else:
                html = str(body)
        else:
            html = str(body)
        
        markdown = md(html, heading_style="ATX")
        return self._clean_markdown(markdown)

    def fetch_local(self, file_path: str) -> str:
        """Read local file and return markdown/text content."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        content = path.read_text(encoding="utf-8")
        
        # If it's HTML, convert to markdown
        if path.suffix.lower() in (".html", ".htm"):
            if HAS_DEPS:
                return self._clean_markdown(md(content, heading_style="ATX"))
            else:
                # Fallback: strip tags
                return re.sub(r"<[^>]+>", "", content)
        
        return content

    def extract_title(self, markdown: str, fallback: str = "") -> str:
        """Extract title from markdown."""
        lines = markdown.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
        return fallback

    def _clean_markdown(self, text: str) -> str:
        """Clean up converted markdown."""
        # Remove excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Remove markdown link references if they are just URLs
        text = re.sub(r"\[([^\]]+)\]\(\1\)", r"\1", text)
        return text.strip()