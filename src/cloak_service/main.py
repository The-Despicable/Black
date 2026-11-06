#!/usr/bin/env python3
"""
Cloak Service — FastAPI wrapper for CloakBrowser stealth browsing.

Endpoints:
  POST /browse         — Navigate to URL, return HTML, cookies, screenshot
  POST /screenshot     — Full-page screenshot
  POST /interact       — Evaluate JavaScript on a page
  POST /research       — Research a query across Sci-Hub, ArXiv, Exploit-DB, GitHub
  GET  /identities     — Tor NEWNYM identity rotation
  GET  /health         — Tor IP + browser availability

Zero Docker dependency — runs as native Python service.
Port: 3401 (matching documentation)
"""

import asyncio
import base64
import logging
import os
import random
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .cloakbrowser import (
    research_paper,
    research_scihub,
    research_arxiv,
    research_exploitdb,
    research_github,
    download_pdf,
    extract_pdf_text,
    USER_AGENTS,
    VIEWPORTS,
    get_random_viewport,
    get_random_user_agent,
)
from cloakbrowser import launch_async as _cb_launch_async
from cloakbrowser import ProxySettings

try:
    from stem import Signal
    from stem.control import Controller
    TOR_AVAILABLE = True
except ImportError:
    TOR_AVAILABLE = False

TOR_PROXY = os.environ.get("TOR_PROXY", "socks5h://127.0.0.1:9050")
TOR_CONTROL = os.environ.get("TOR_CONTROL", "127.0.0.1:9051")
TOR_PASSWORD = os.environ.get("TOR_PASSWORD", "")
PORT = int(os.environ.get("PORT", "3401"))  # Fixed: was 3400 in Dockerfile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cloak-service")

# Browser session handle (set at startup)
_browser = None  # Playwright Browser object
_browser_ready = False


# ── Request/Response models ──
class BrowseRequest(BaseModel):
    url: str
    wait_selector: Optional[str] = None
    timeout: int = 30000
    viewport: Optional[dict] = None
    proxy: Optional[str] = None


class BrowseResponse(BaseModel):
    url: str
    title: str
    html: str
    screenshot: Optional[str]
    cookies: list
    headers: dict
    timing: float


class ScreenshotRequest(BaseModel):
    url: str
    full_page: bool = True
    viewport: Optional[dict] = None


class ScreenshotResponse(BaseModel):
    screenshot: Optional[str]
    url: str


class InteractRequest(BaseModel):
    url: str
    script: str
    wait_for: Optional[str] = None


class InteractResponse(BaseModel):
    result: Any
    url: str


class ResearchRequest(BaseModel):
    query: str
    sources: Optional[list[str]] = None
    proxy: Optional[str] = None
    download_pdfs: bool = False
    pdf_dir: str = "./research_pdfs"


class ResearchResponse(BaseModel):
    query: str
    results: list[dict]
    total_sources: int


class IdentityResponse(BaseModel):
    status: str
    new_ip: Optional[str]
    old_ip: Optional[str]


class HealthResponse(BaseModel):
    status: str
    tor_ip: Optional[str]
    browser_available: bool


# ── Tor helpers ──
async def get_tor_ip() -> Optional[str]:
    try:
        async with httpx.AsyncClient(proxies=TOR_PROXY, timeout=10) as client:
            r = await client.get("https://httpbin.org/ip")
            return r.json().get("origin")
    except Exception:
        try:
            async with httpx.AsyncClient(proxies=TOR_PROXY, timeout=10) as client:
                r = await client.get("https://api.ipify.org?format=json")
                return r.json().get("ip")
        except Exception:
            return None


def rotate_tor_identity() -> bool:
    if not TOR_AVAILABLE:
        logger.warning("Tor (stem) not available — skipping identity rotation")
        return False
    try:
        host, port_str = TOR_CONTROL.split(":")
        port = int(port_str)
        with Controller.from_port(address=host, port=port) as controller:
            if TOR_PASSWORD:
                controller.authenticate(password=TOR_PASSWORD)
            else:
                controller.authenticate()
            controller.signal(Signal.NEWNYM)
        return True
    except Exception as e:
        logger.error(f"Tor identity rotation failed: {e}")
        return False


# ── Browser management ──
async def _launch_browser(proxy: Optional[str] = None):
    """Launch a real CloakBrowser Playwright browser."""
    global _browser
    proxy_settings = None
    if proxy:
        proxy_settings = {"server": proxy}
    _browser = await _cb_launch_async(
        headless=True,
        proxy=proxy_settings,
        stealth_args=True,
    )
    return _browser


async def _get_page(viewport: Optional[dict] = None, proxy: Optional[str] = None):
    """Get a Playwright page from the global browser, launching if needed."""
    global _browser
    if _browser is None:
        await _launch_browser(proxy=proxy)
    context = await _browser.new_context(
        viewport=viewport or get_random_viewport(),
        user_agent=get_random_user_agent(),
        ignore_https_errors=True,
        java_script_enabled=True,
    )
    page = await context.new_page()
    return page, context


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _browser, _browser_ready
    logger.info("Starting cloak-service on port %d...", PORT)
    try:
        await _launch_browser(proxy=TOR_PROXY)
        _browser_ready = True
        logger.info("CloakBrowser launched successfully")
    except Exception as e:
        logger.error("CloakBrowser launch failed: %s", e)
        _browser = None
        _browser_ready = False
    yield
    logger.info("Shutting down cloak-service...")
    if _browser:
        try:
            await _browser.close()
        except Exception:
            pass


app = FastAPI(
    title="Cloak Service",
    version="2.0.0",
    description="Stealth browsing service powered by CloakBrowser",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start
    logger.info("%s %s -> %s (%.3fs)", request.method, request.url.path, response.status_code, elapsed)
    return response


# ── Endpoints ──
@app.post("/browse", response_model=BrowseResponse)
async def browse(req: BrowseRequest):
    if not _browser_ready:
        raise HTTPException(status_code=503, detail="Browser not available")

    start = time.time()
    page = None
    context = None
    try:
        page, context = await _get_page(viewport=req.viewport, proxy=req.proxy or TOR_PROXY)
        try:
            resp = await page.goto(req.url, wait_until="networkidle", timeout=req.timeout)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Navigation failed: {e}")
        if req.wait_selector:
            try:
                await page.wait_for_selector(req.wait_selector, timeout=req.timeout)
            except Exception:
                pass
        title = await page.title()
        html = await page.content()
        screenshot_b64 = None
        try:
            screenshot_bytes = await page.screenshot(full_page=True, type="png")
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
        except Exception:
            pass
        cookies = await context.cookies()
        headers = resp.headers if resp else {}
        timing = time.time() - start
        return BrowseResponse(
            url=page.url,
            title=title,
            html=html,
            screenshot=screenshot_b64,
            cookies=cookies,
            headers=dict(headers),
            timing=timing,
        )
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass
        if context:
            try:
                await context.close()
            except Exception:
                pass


@app.post("/screenshot", response_model=ScreenshotResponse)
async def screenshot(req: ScreenshotRequest):
    if not _browser_ready:
        raise HTTPException(status_code=503, detail="Browser not available")

    page = None
    context = None
    try:
        page, context = await _get_page(viewport=req.viewport, proxy=TOR_PROXY)
        try:
            await page.goto(req.url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Navigation failed: {e}")
        img_b64 = None
        try:
            screenshot_bytes = await page.screenshot(full_page=req.full_page, type="png")
            img_b64 = base64.b64encode(screenshot_bytes).decode()
        except Exception:
            pass
        return ScreenshotResponse(screenshot=img_b64, url=page.url)
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass
        if context:
            try:
                await context.close()
            except Exception:
                pass


@app.post("/interact", response_model=InteractResponse)
async def interact(req: InteractRequest):
    if not _browser_ready:
        raise HTTPException(status_code=503, detail="Browser not available")

    page = None
    context = None
    try:
        page, context = await _get_page(proxy=TOR_PROXY)
        try:
            await page.goto(req.url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Navigation failed: {e}")
        if req.wait_for:
            try:
                await page.wait_for_function(req.wait_for, timeout=30000)
            except Exception:
                pass
        result = await page.evaluate(req.script)
        return InteractResponse(result=result, url=page.url)
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass
        if context:
            try:
                await context.close()
            except Exception:
                pass


@app.post("/research", response_model=ResearchResponse)
async def research(req: ResearchRequest):
    """Research a query across multiple sources (Sci-Hub, ArXiv, Exploit-DB, GitHub)."""
    try:
        results = await research_paper(
            query=req.query,
            sources=req.sources,
            proxy=req.proxy or TOR_PROXY,
            download_pdfs=req.download_pdfs,
            pdf_dir=req.pdf_dir,
        )
        return ResearchResponse(
            query=req.query,
            results=results,
            total_sources=len(results),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Research failed: {e}")


@app.get("/identities", response_model=IdentityResponse)
async def identities():
    old_ip = await get_tor_ip()
    success = rotate_tor_identity()
    if not success:
        raise HTTPException(status_code=502, detail="Tor identity rotation failed")
    await asyncio.sleep(2)
    new_ip = await get_tor_ip()
    return IdentityResponse(
        status="rotated" if new_ip != old_ip else "unchanged",
        new_ip=new_ip,
        old_ip=old_ip,
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    tor_ip = await get_tor_ip()
    return HealthResponse(
        status="ok" if tor_ip and _browser_ready else "degraded",
        tor_ip=tor_ip,
        browser_available=_browser_ready,
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
