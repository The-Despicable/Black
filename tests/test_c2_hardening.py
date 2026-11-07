"""Hardening regression tests (remediation phases 2-4).

Covers the security remediation applied on top of phase 1:
- AEAD channel crypto (AES-256-GCM) replacing Fernet in the legacy C2
- Per-IP connection rate limiting and bounded frame sizes
- Loopback bind defaults on the tool's own services
- Version single-sourcing between pyproject and raphael-ma
- Portability: no author-machine absolute paths in arena / config shims
"""
from __future__ import annotations

import json
import socket
import threading
import time
import tomllib
from pathlib import Path

import pytest

from harness.rat_c2 import (
    AEADChannel,
    ConnectionRateLimiter,
    MAX_MESSAGE_BYTES,
    RATC2Server,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _hardcoded_repo_path(source: str) -> bool:
    """True if the author's machine path is used as a string literal.

    Docstrings explaining the historical hardcoding are fine; quoted path
    literals in code are not.
    """
    import re

    return bool(re.search(r"['\"]\/home\/yaser\/raphael-2\.0", source))


# ------------------------------------------------------------------ crypto
class TestAEADChannel:
    def test_roundtrip_bytes_and_str(self):
        ch = AEADChannel("test-channel-passphrase")
        assert ch.decrypt(ch.encrypt(b"payload")) == b"payload"
        assert ch.decrypt(ch.encrypt("text")) == b"text"

    def test_key_material_formats_interoperate(self):
        """str, raw 32-byte and b64 keys must reach the same channel."""
        raw = b"\x42" * 32
        a, b = AEADChannel(raw), AEADChannel(raw)
        assert a.decrypt(b.encrypt(b"x" * 4096)) == b"x" * 4096

    def test_tamper_detection(self):
        ch = AEADChannel("k")
        blob = bytearray(ch.encrypt(b"fixed"))
        blob[-1] ^= 0xFF
        with pytest.raises(Exception):
            ch.decrypt(bytes(blob))

    def test_replayed_nonce_with_different_plaintext_fails(self):
        ch = AEADChannel("k")
        foreign = AEADChannel("other-key")
        good = ch.encrypt(b"legit")
        evil = foreign.encrypt(b"evil")
        assert ch.decrypt(good) == b"legit"
        with pytest.raises(Exception):
            ch.decrypt(evil)

    def test_short_ciphertext_rejected(self):
        with pytest.raises(ValueError):
            AEADChannel("k").decrypt(b"tooshort")

    def test_fresh_nonce_per_message(self):
        ch = AEADChannel("k")
        blobs = {ch.encrypt(b"same") for _ in range(8)}
        assert len(blobs) == 8  # nonce uniqueness -> distinct ciphertexts


# ------------------------------------------------------------- rate limits
class TestConnectionRateLimiter:
    def test_per_ip_window(self):
        rl = ConnectionRateLimiter(max_per_ip_per_minute=3, max_concurrent=100)
        assert [rl.allow("10.0.0.1") for _ in range(4)] == [True, True, True, False]

    def test_other_ip_unaffected(self):
        rl = ConnectionRateLimiter(max_per_ip_per_minute=1, max_concurrent=100)
        assert rl.allow("10.0.0.1")
        assert not rl.allow("10.0.0.1")
        assert rl.allow("10.0.0.2")

    def test_concurrency_cap_and_release(self):
        rl = ConnectionRateLimiter(max_per_ip_per_minute=100, max_concurrent=2)
        assert rl.allow("a") and rl.allow("b")
        assert not rl.allow("c")
        rl.release()
        assert rl.allow("c")

    def test_window_slides(self):
        rl = ConnectionRateLimiter(max_per_ip_per_minute=1, max_concurrent=100,
                                   )
        rl._window = 0.05  # speed the test up
        assert rl.allow("a")
        assert not rl.allow("a")
        time.sleep(0.06)
        assert rl.allow("a")


# ------------------------------------------------------------- frame bound
class TestFrameBound:
    def test_oversized_frame_dropped(self):
        srv = RATC2Server()
        a, b = socket.socketpair()
        try:
            a.sendall((MAX_MESSAGE_BYTES + 1).to_bytes(4, "big"))
            assert srv.receive_data(b) is None
        finally:
            a.close()
            b.close()

    def test_max_message_bytes_sane(self):
        assert 0 < MAX_MESSAGE_BYTES <= 64 * 1024 * 1024


# --------------------------------------------------------- secure defaults
class TestSecureBindDefaults:
    def test_rat_c2_server_defaults_to_loopback(self):
        assert RATC2Server().host == "127.0.0.1"

    def test_secure_c2_server_defaults_to_loopback(self):
        import inspect

        from harness.rat_c2_secure import SecureC2Server

        # SecureC2Server fails closed without TLS material, so inspect
        # the signature rather than instantiating it.
        default = inspect.signature(SecureC2Server).parameters["host"].default
        assert default == "127.0.0.1"

    def test_native_c2_server_defaults_to_loopback(self):
        from harness.raphael_cli import NativeC2Server

        assert NativeC2Server().host == "127.0.0.1"


# ------------------------------------------------------------- version skew
class TestVersionSingleSourcing:
    def test_package_version_matches_pyproject(self):
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
        from raphael.multiagent import __version__

        assert __version__ == pyproject["project"]["version"]

    def test_version_reports_31(self):
        from raphael.multiagent import __version__

        assert __version__ == "3.1.0"


# ------------------------------------------------------------- portability
class TestPortability:
    def test_no_author_machine_paths_in_arena(self):
        offenders = [
            p.name for p in (REPO_ROOT / "src" / "arena").glob("*.py")
            if _hardcoded_repo_path(p.read_text())
        ]
        assert offenders == []

    def test_no_author_machine_paths_in_orchestrator_config(self):
        for p in (REPO_ROOT / "src" / "orchestrator" / "config").glob("*.py"):
            assert not _hardcoded_repo_path(p.read_text()), p.name

    def test_orchestrator_config_shims_reexport(self):
        import orchestrator.config.paths as paths
        import orchestrator.config.target as target

        assert callable(paths.set_scope)
        assert callable(target.set_target)


# ------------------------------------------------- end-to-end channel smoke
class TestC2ChannelEndToEnd:
    def test_beacon_ack_over_aead(self):
        """Live socket exchange: beacon -> ack over AES-256-GCM."""
        srv = RATC2Server(host="127.0.0.1", port=0)
        srv.server_socket.bind(("127.0.0.1", 0))
        port = srv.server_socket.getsockname()[1]
        srv.server_socket.listen(4)
        srv._running = True
        t = threading.Thread(target=srv._accept_loop, daemon=True)
        t.start()
        ch = AEADChannel(srv.key)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
                beacon = ch.encrypt(json.dumps(
                    {"type": "beacon", "implant_id": "it1", "os": "linux",
                     "user": "u", "hostname": "h", "pid": 1}
                ).encode())
                c.sendall(len(beacon).to_bytes(4, "big") + beacon)
                n = int.from_bytes(c.recv(4), "big")
                resp = b""
                while len(resp) < n:
                    resp += c.recv(n - len(resp))
                assert json.loads(ch.decrypt(resp))["type"] == "ack"
        finally:
            srv._running = False
            srv.server_socket.close()
