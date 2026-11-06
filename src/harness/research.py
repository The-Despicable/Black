"""
harness.research — Research bundle normalization for BlackHatHarness.

Provides BundleNormalizer for normalizing research results from
various sources (Sci-Hub, Exploit-DB, GitHub, etc.).
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ResearchBundle:
    """Normalized research bundle."""
    source: str
    url: str
    title: str
    authors: List[str] = field(default_factory=list)
    abstract: str = ""
    text: str = ""
    cves: List[str] = field(default_factory=list)

    @classmethod
    def normalize(cls, source: str, url: str, data: dict) -> "ResearchBundle":
        """Normalize raw research data into a bundle."""
        title = data.get("title", "")
        authors = data.get("authors", [])
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(",")]
        abstract = data.get("abstract", "")
        text = data.get("text", "")
        cves = data.get("cves", [])
        if not cves and text:
            # Extract CVEs from text
            cves = re.findall(r"CVE-\d{4}-\d{4,7}", text)
        return cls(
            source=source,
            url=url,
            title=title,
            authors=authors,
            abstract=abstract,
            text=text,
            cves=cves,
        )


class BundleNormalizer:
    """Normalizes research bundles from multiple sources."""

    def normalize(self, source: str, url: str, data: dict) -> ResearchBundle:
        """Normalize a research result."""
        return ResearchBundle.normalize(source, url, data)
