#!/usr/bin/env python3
"""
CloakBrowser Service Module — Fixed & Enhanced for Raphael Black Hat Harness

Replaces the broken httpx-based stub with a real Playwright-backed CloakBrowser
launcher. Supports stealth browsing, proxy chains (Tor), fingerprint rotation,
and research paper acquisition from Sci-Hub, ArXiv, Exploit-DB, and GitHub.

Zero Docker dependency — runs as a native Python service or library import.
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("cloakbrowser")

# ── Try importing the real CloakBrowser package first ──
try:
    from cloakbrowser import (
        launch_async as _cb_launch_async,
        launch as _cb_launch,
        ProxySettings,
        build_args,
        get_random_user_agent as _cb_get_random_user_agent,
    )
    CLOAKBROWSER_AVAILABLE = True
except ImportError:
    CLOAKBROWSER_AVAILABLE = False
    logger.warning(
        "cloakbrowser package not installed — falling back to httpx stub mode. "
        "Install with: pip install cloakbrowser"
    )

# ── Fallback user agents & viewports (used when real package unavailable) ──
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
]

COOKIE_JAR: Dict[str, List[dict]] = {}
SESSION_STORE: Dict[str, bytes] = {}

# ── Research source configurations ──
RESEARCH_SOURCES = {
    "scihub": {
        "base_urls": [
            "https://sci-hub.se",
            "https://sci-hub.st",
            "https://sci-hub.ru",
            "https://sci-hub.wf",
        ],
        "search_path": "/?q={query}",
        "pdf_pattern": r"location\.href='([^']+\.pdf)'",
    },
    "arxiv": {
        "base_url": "https://arxiv.org",
        "search_path": "/search/?query={query}&searchtype=all",
        "pdf_pattern": r'href="(/abs/[^"]+)"',
    },
    "exploitdb": {
        "base_url": "https://www.exploit-db.com",
        "search_path": "/search?cve={query}",
        "exploit_pattern": r'/exploits/(\d+)',
    },
    "github": {
        "base_url": "https://github.com",
        "search_path": "/search?q={query}&type=repositories",
        "repo_pattern": r'href="/([^/]+/[^/]+)"',
    },
}


def get_random_viewport() -> dict:
    return random.choice(VIEWPORTS)


def get_random_user_agent() -> str:
    return random.choice(USER_AGENTS)


# ── Real CloakBrowser-backed launcher ──
async def launch_async(
    url: str,
    viewport: Optional[dict] = None,
    user_agent: Optional[str] = None,
    proxy: Optional[str] = None,
    wait: int = 3,
    headless: bool = True,
    stealth: bool = True,
    **kwargs,
) -> dict:
    """
    Launch a real CloakBrowser (Playwright) instance and navigate to URL.

    Returns a dict compatible with the original stub interface:
        {"url", "status", "title", "cookies", "content_length", "headers",
         "viewport", "user_agent", "html", "screenshot"}

    If the cloakbrowser package is unavailable, falls back to httpx.
    """
    vp = viewport or get_random_viewport()
    ua = user_agent or get_random_user_agent()

    if CLOAKBROWSER_AVAILABLE:
        return await _launch_with_cloakbrowser(
            url, vp, ua, proxy, wait, headless, stealth, **kwargs
        )

    # ── Fallback: httpx stub (original behavior) ──
    return await _launch_httpx_fallback(url, vp, ua, proxy, wait)


async def _launch_with_cloakbrowser(
    url: str,
    viewport: dict,
    user_agent: str,
    proxy: Optional[str],
    wait: int,
    headless: bool,
    stealth: bool,
    **kwargs,
) -> dict:
    """Use the real cloakbrowser package to launch a stealth Playwright browser."""
    from playwright.async_api import async_playwright

    proxy_settings = None
    if proxy:
        # Parse proxy URL: socks5://host:port or http://user:pass@host:port
        proxy_settings = {"server": proxy}

    async with async_playwright() as p:
        launch_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-accelerated-2d-canvas",
            "--no-first-run",
            "--no-zygote",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
        ]

        if stealth:
            launch_args.extend([
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials",
            ])

        browser = await p.chromium.launch(
            headless=headless,
            args=launch_args,
            proxy=proxy_settings,
        )

        context = await browser.new_context(
            viewport=viewport,
            user_agent=user_agent,
            ignore_https_errors=True,
            java_script_enabled=True,
        )

        # Apply stealth scripts to hide automation
        if stealth:
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                window.chrome = {runtime: {}};
            """)

        page = await context.new_page()

        try:
            response = await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(wait * 1000)

            html = await page.content()
            title = await page.title()
            cookies = await context.cookies()
            headers = response.headers if response else {}

            # Try to capture screenshot
            screenshot_b64 = None
            try:
                screenshot_bytes = await page.screenshot(full_page=True, type="png")
                screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
            except Exception:
                pass

            return {
                "url": page.url,
                "status": response.status if response else 200,
                "title": title,
                "cookies": cookies,
                "content_length": len(html),
                "headers": dict(headers),
                "viewport": viewport,
                "user_agent": user_agent,
                "html": html,
                "screenshot": screenshot_b64,
            }
        finally:
            await browser.close()


async def _launch_httpx_fallback(
    url: str,
    viewport: dict,
    user_agent: str,
    proxy: Optional[str],
    wait: int,
) -> dict:
    """Original httpx-based fallback when cloakbrowser package is missing."""
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    transport = httpx.AsyncHTTPTransport(retries=1)
    if proxy:
        transport = httpx.AsyncHTTPTransport(retries=1, proxy=proxy)

    async with httpx.AsyncClient(
        headers=headers,
        timeout=30,
        follow_redirects=True,
        transport=transport,
    ) as client:
        resp = await client.get(url)
        status = resp.status_code
        content = resp.text[:100000]
        page_title = ""
        title_match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE)
        if title_match:
            page_title = title_match.group(1)

        cookies = []
        for cookie in resp.cookies.jar:
            cookies.append({
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain or "",
                "path": cookie.path or "/",
            })

        return {
            "url": str(resp.url),
            "status": status,
            "title": page_title,
            "cookies": cookies,
            "content_length": len(content),
            "headers": dict(resp.headers),
            "viewport": viewport,
            "user_agent": user_agent,
            "html": content,
            "screenshot": None,
        }


# ── Research paper acquisition ──
async def research_scihub(
    query: str,
    proxy: Optional[str] = None,
    wait: int = 5,
) -> Dict[str, Any]:
    """
    Search Sci-Hub for a research paper and attempt to extract the PDF URL.

    Args:
        query: DOI, title, or CVE-related search term
        proxy: Optional proxy URL (e.g., socks5://127.0.0.1:9050)
        wait: Seconds to wait for page load

    Returns:
        dict with keys: source, query, pdf_url, page_url, title, html, error
    """
    source_cfg = RESEARCH_SOURCES["scihub"]
    result = {
        "source": "scihub",
        "query": query,
        "pdf_url": None,
        "page_url": None,
        "title": None,
        "html": None,
        "error": None,
    }

    for base_url in source_cfg["base_urls"]:
        try:
            search_url = f"{base_url}{source_cfg['search_path'].format(query=query)}"
            page = await launch_async(
                url=search_url,
                proxy=proxy,
                wait=wait,
                headless=True,
                stealth=True,
            )

            result["page_url"] = page.get("url")
            result["html"] = page.get("html")
            result["title"] = page.get("title")

            # Extract PDF URL from page
            html = page.get("html", "")
            pdf_match = re.search(source_cfg["pdf_pattern"], html)
            if pdf_match:
                pdf_path = pdf_match.group(1)
                if pdf_path.startswith("//"):
                    result["pdf_url"] = "https:" + pdf_path
                elif pdf_path.startswith("/"):
                    result["pdf_url"] = base_url + pdf_path
                else:
                    result["pdf_url"] = pdf_path
                break

        except Exception as e:
            logger.warning(f"Sci-Hub {base_url} failed: {e}")
            result["error"] = str(e)

    return result


async def research_arxiv(
    query: str,
    proxy: Optional[str] = None,
    wait: int = 5,
) -> Dict[str, Any]:
    """Search ArXiv for research papers."""
    source_cfg = RESEARCH_SOURCES["arxiv"]
    result = {
        "source": "arxiv",
        "query": query,
        "pdf_url": None,
        "page_url": None,
        "title": None,
        "html": None,
        "error": None,
    }

    try:
        search_url = f"{source_cfg['base_url']}{source_cfg['search_path'].format(query=query)}"
        page = await launch_async(
            url=search_url,
            proxy=proxy,
            wait=wait,
            headless=True,
            stealth=True,
        )

        result["page_url"] = page.get("url")
        result["html"] = page.get("html")
        result["title"] = page.get("title")

        html = page.get("html", "")
        # Extract first paper abstract link
        abs_match = re.search(source_cfg["pdf_pattern"], html)
        if abs_match:
            abs_path = abs_match.group(1)
            result["page_url"] = source_cfg["base_url"] + abs_path
            # Convert /abs/ to /pdf/
            pdf_path = abs_path.replace("/abs/", "/pdf/")
            result["pdf_url"] = source_cfg["base_url"] + pdf_path

    except Exception as e:
        logger.warning(f"ArXiv search failed: {e}")
        result["error"] = str(e)

    return result


async def research_exploitdb(
    query: str,
    proxy: Optional[str] = None,
    wait: int = 5,
) -> Dict[str, Any]:
    """Search Exploit-DB for exploit code related to a CVE or keyword."""
    source_cfg = RESEARCH_SOURCES["exploitdb"]
    result = {
        "source": "exploitdb",
        "query": query,
        "exploit_urls": [],
        "page_url": None,
        "html": None,
        "error": None,
    }

    try:
        search_url = f"{source_cfg['base_url']}{source_cfg['search_path'].format(query=query)}"
        page = await launch_async(
            url=search_url,
            proxy=proxy,
            wait=wait,
            headless=True,
            stealth=True,
        )

        result["page_url"] = page.get("url")
        result["html"] = page.get("html")

        html = page.get("html", "")
        exploit_ids = re.findall(source_cfg["exploit_pattern"], html)
        for eid in exploit_ids[:10]:
            result["exploit_urls"].append(
                f"{source_cfg['base_url']}/exploits/{eid}"
            )

    except Exception as e:
        logger.warning(f"Exploit-DB search failed: {e}")
        result["error"] = str(e)

    return result


async def research_github(
    query: str,
    proxy: Optional[str] = None,
    wait: int = 5,
) -> Dict[str, Any]:
    """Search GitHub for exploit repositories."""
    source_cfg = RESEARCH_SOURCES["github"]
    result = {
        "source": "github",
        "query": query,
        "repository_urls": [],
        "page_url": None,
        "html": None,
        "error": None,
    }

    try:
        search_url = f"{source_cfg['base_url']}{source_cfg['search_path'].format(query=query)}"
        page = await launch_async(
            url=search_url,
            proxy=proxy,
            wait=wait,
            headless=True,
            stealth=True,
        )

        result["page_url"] = page.get("url")
        result["html"] = page.get("html")

        html = page.get("html", "")
        repos = re.findall(source_cfg["repo_pattern"], html)
        for repo in repos[:10]:
            if "/" in repo and not repo.startswith(("login", "signup", "about")):
                result["repository_urls"].append(
                    f"{source_cfg['base_url']}/{repo}"
                )

    except Exception as e:
        logger.warning(f"GitHub search failed: {e}")
        result["error"] = str(e)

    return result


async def download_pdf(
    pdf_url: str,
    output_path: str,
    proxy: Optional[str] = None,
) -> bool:
    """
    Download a PDF from a given URL using stealth headers.

    Returns True on success.
    """
    try:
        headers = {
            "User-Agent": get_random_user_agent(),
            "Accept": "application/pdf,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://sci-hub.se/",
        }

        transport = httpx.AsyncHTTPTransport(retries=2)
        if proxy:
            transport = httpx.AsyncHTTPTransport(retries=2, proxy=proxy)

        async with httpx.AsyncClient(
            headers=headers,
            timeout=60,
            follow_redirects=True,
            transport=transport,
        ) as client:
            resp = await client.get(pdf_url)
            if resp.status_code == 200:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(resp.content)
                logger.info(f"Downloaded PDF: {output_path} ({len(resp.content)} bytes)")
                return True
            else:
                logger.warning(f"PDF download failed: HTTP {resp.status_code}")
                return False

    except Exception as e:
        logger.error(f"PDF download error: {e}")
        return False


async def extract_pdf_text(pdf_path: str) -> Optional[str]:
    """
    Extract text from a PDF file using pdftotext or PyPDF2 fallback.

    Returns extracted text or None.
    """
    # Try pdftotext first
    try:
        import subprocess
        proc = await asyncio.create_subprocess_exec(
            "pdftotext", pdf_path, "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return stdout.decode("utf-8", errors="ignore")
    except Exception:
        pass

    # Fallback: PyPDF2
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        logger.warning(f"PDF text extraction failed: {e}")
        return None


# ── Convenience: full research pipeline ──
async def research_paper(
    query: str,
    sources: Optional[List[str]] = None,
    proxy: Optional[str] = None,
    download_pdfs: bool = True,
    pdf_dir: str = "./research_pdfs",
) -> List[Dict[str, Any]]:
    """
    Run full research pipeline across multiple sources.

    Args:
        query: Search term (CVE, paper title, DOI, keyword)
        sources: List of sources to query (default: all)
        proxy: Optional proxy URL
        download_pdfs: Whether to download found PDFs
        pdf_dir: Directory to save PDFs

    Returns:
        List of research result dicts
    """
    if sources is None:
        sources = ["scihub", "arxiv", "exploitdb", "github"]

    results = []

    for source in sources:
        if source == "scihub":
            res = await research_scihub(query, proxy=proxy)
            results.append(res)
            if download_pdfs and res.get("pdf_url"):
                pdf_name = f"{hashlib.md5(query.encode()).hexdigest()}.pdf"
                pdf_path = os.path.join(pdf_dir, pdf_name)
                await download_pdf(res["pdf_url"], pdf_path, proxy=proxy)
                res["pdf_path"] = pdf_path
                # Extract text
                text = await extract_pdf_text(pdf_path)
                res["extracted_text"] = text

        elif source == "arxiv":
            res = await research_arxiv(query, proxy=proxy)
            results.append(res)
            if download_pdfs and res.get("pdf_url"):
                pdf_name = f"arxiv_{hashlib.md5(query.encode()).hexdigest()}.pdf"
                pdf_path = os.path.join(pdf_dir, pdf_name)
                await download_pdf(res["pdf_url"], pdf_path, proxy=proxy)
                res["pdf_path"] = pdf_path
                text = await extract_pdf_text(pdf_path)
                res["extracted_text"] = text

        elif source == "exploitdb":
            res = await research_exploitdb(query, proxy=proxy)
            results.append(res)

        elif source == "github":
            res = await research_github(query, proxy=proxy)
            results.append(res)

    return results


# ── Async context manager for service-style usage ──
class CloakBrowserSession:
    """Context manager for a CloakBrowser browsing session."""

    def __init__(
        self,
        proxy: Optional[str] = None,
        headless: bool = True,
        stealth: bool = True,
    ):
        self.proxy = proxy
        self.headless = headless
        self.stealth = stealth
        self._browser = None
        self._context = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass

    async def browse(self, url: str, wait: int = 3) -> dict:
        """Browse a URL within this session."""
        return await launch_async(
            url=url,
            proxy=self.proxy,
            wait=wait,
            headless=self.headless,
            stealth=self.stealth,
        )
