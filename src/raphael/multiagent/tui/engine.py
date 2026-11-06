"""Engine adapter — the ONLY module that imports ``raphael.multiagent.*``.

The TUI talks to the CLI exactly the way the CLI defines itself:

* commands are executed by invoking the existing Typer app object in-process
  (``typer.main.get_command`` -> click ``main(standalone_mode=False)``), so
  governance, the SQLite brain, orchestrators, providers and transcripts all
  behave precisely as on the command line — including exit codes 0 / 3 / 4;
* stdout / stderr are captured with thread-safe line taps so screens can
  stream CLI output live while a worker thread runs the command;
* read-only facts (config.yaml, transcripts/, audit log) come from the
  documented data locations.

No business logic is re-implemented here.
"""

from __future__ import annotations

import importlib
import io
import os
import re
import threading
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

EXIT_OK = 0
EXIT_KILL_SWITCH = 3
EXIT_GOVERNANCE_CONFIG = 4
EXIT_ENGINE_UNAVAILABLE = -1

OUTCOME_LABELS = {
    EXIT_OK: "success",
    EXIT_KILL_SWITCH: "governance kill-switch abort",
    EXIT_GOVERNANCE_CONFIG: "governance config error",
    EXIT_ENGINE_UNAVAILABLE: "engine unavailable",
}

CLI_MODULE = "raphael.multiagent.cli"
PROG_NAME = "raphael-ma"

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    """CLI output captured from a non-tty stream is ANSI-free, but a console
    created with force_terminal would embed escapes — never show them raw."""
    return _ANSI_RE.sub("", text)


@dataclass
class RunResult:
    argv: List[str]
    code: int
    out: str = ""
    err: str = ""
    duration: float = 0.0

    @property
    def ok(self) -> bool:
        return self.code == EXIT_OK

    @property
    def outcome(self) -> str:
        return OUTCOME_LABELS.get(self.code, f"exit {self.code}")

    @property
    def out_lines(self) -> List[str]:
        return self.out.split("\n") if self.out else []

    @property
    def err_lines(self) -> List[str]:
        return self.err.split("\n") if self.err else []

    @property
    def label(self) -> str:
        base = f"exit {self.code} · {self.outcome}"
        if self.code == EXIT_KILL_SWITCH:
            base += " — session aborted & audited"
        elif self.code == EXIT_GOVERNANCE_CONFIG:
            base += " — check governance config"
        elif self.code == EXIT_ENGINE_UNAVAILABLE:
            base += " — set PYTHONPATH to the repo src/ dir"
        return base


class _Tap(io.TextIOBase):
    """Thread-safe stdout/stderr tap: drains new lines incrementally while
    keeping a full transcript for the final RunResult."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending = ""
        self._fresh: List[str] = []
        self._all: List[str] = []

    # TextIOBase plumbing ------------------------------------------------
    def writable(self) -> bool:
        return True

    @property
    def encoding(self) -> str:
        return "utf-8"

    @property
    def errors(self) -> str:
        return "replace"

    def write(self, s: str) -> int:  # type: ignore[override]
        if not s:
            return 0
        with self._lock:
            self._pending += s
            while "\n" in self._pending:
                line, self._pending = self._pending.split("\n", 1)
                self._fresh.append(line)
                self._all.append(line)
        return len(s)

    def flush(self) -> None:  # type: ignore[override]
        pass

    # tap API -------------------------------------------------------------
    def drain(self) -> List[str]:
        with self._lock:
            out = self._fresh
            self._fresh = []
            if self._pending:
                out = out + [self._pending]
                self._all.append(self._pending)
                self._pending = ""
        return out

    def text(self) -> str:
        return "\n".join(self._all)


class Engine:
    """Runs the real Typer command surface in-process, serialized."""

    def __init__(self, home: Optional[str] = None) -> None:
        self._home = str(home) if home else None
        self._run_lock = threading.Lock()
        self._import_lock = threading.Lock()
        self._cmd = None
        self._module_path: Optional[str] = None
        self._import_error: Optional[str] = None
        self._active_out: Optional[_Tap] = None
        self._active_err: Optional[_Tap] = None

    # ------------------------------------------------------------------
    @property
    def home(self) -> Optional[str]:
        return self._home

    def _ensure_env(self) -> None:
        if self._home:
            os.environ["RAPHAEL_MA_HOME"] = self._home

    def probe(self) -> tuple:
        """Try importing the real CLI. Returns (ok, module_file, error)."""
        try:
            self._ensure_env()
            mod = importlib.import_module(CLI_MODULE)
            path = getattr(mod, "__file__", None) or "?"
            self._module_path = str(path)
            return True, str(path), None
        except Exception as exc:  # noqa: BLE001 — report, never crash the TUI
            self._import_error = f"{type(exc).__name__}: {exc}"
            return False, None, self._import_error

    def _command(self):
        with self._import_lock:
            if self._cmd is not None:
                return self._cmd
            self._ensure_env()
            mod = importlib.import_module(CLI_MODULE)
            typer_app = mod.app
            from typer.main import get_command

            self._cmd = get_command(typer_app)
            self._module_path = str(getattr(mod, "__file__", "?"))
            return self._cmd

    # ------------------------------------------------------------------
    def poll_out_lines(self) -> List[str]:
        tap = self._active_out
        return tap.drain() if tap is not None else []

    def poll_err_lines(self) -> List[str]:
        tap = self._active_err
        return tap.drain() if tap is not None else []

    # ------------------------------------------------------------------
    def run(self, argv: Sequence[str]) -> RunResult:
        """Execute ``raphael-ma <argv>`` in-process and return the outcome."""
        argv = [str(a) for a in argv]
        t0 = time.monotonic()
        with self._run_lock:
            out_tap, err_tap = _Tap(), _Tap()
            self._active_out, self._active_err = out_tap, err_tap
            restore: List[tuple] = []
            try:
                self._ensure_env()
                # Keep captured Rich tables readable (non-tty width).
                if "COLUMNS" not in os.environ:
                    os.environ["COLUMNS"] = "100"
                    restore.append(("COLUMNS", None))
                # The CLI's log.py is environment-driven.
                if ("--verbose" in argv or "-v" in argv) and "RAPHAEL_MA_LOG" not in os.environ:
                    os.environ["RAPHAEL_MA_LOG"] = "debug"
                    restore.append(("RAPHAEL_MA_LOG", None))

                try:
                    cmd = self._command()
                except Exception as exc:  # noqa: BLE001
                    return RunResult(
                        argv,
                        EXIT_ENGINE_UNAVAILABLE,
                        "",
                        "cannot import raphael.multiagent.cli — set PYTHONPATH to the "
                        f"repository src/ directory.\n{type(exc).__name__}: {exc}",
                        time.monotonic() - t0,
                    )

                from click.exceptions import Abort, ClickException

                code = EXIT_OK
                try:
                    with redirect_stdout(out_tap), redirect_stderr(err_tap):
                        rv = cmd.main(
                            args=argv,
                            standalone_mode=False,
                            prog_name=PROG_NAME,
                        )
                        code = rv if isinstance(rv, int) else EXIT_OK
                except SystemExit as exc:
                    code = int(exc.code or EXIT_OK)
                except ClickException as exc:
                    code = int(getattr(exc, "exit_code", 1) or 1)
                    err_tap.write(str(exc.format_message()) + "\n")
                except Abort:
                    code = 130
                except Exception:  # noqa: BLE001 — surface crashes honestly
                    code = 1
                    err_tap.write(traceback.format_exc())

                out_tap.drain()
                err_tap.drain()
                return RunResult(
                    argv,
                    code,
                    strip_ansi(out_tap.text()),
                    strip_ansi(err_tap.text()),
                    time.monotonic() - t0,
                )
            finally:
                for key, old in restore:
                    if old is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = old
                self._active_out = None
                self._active_err = None
