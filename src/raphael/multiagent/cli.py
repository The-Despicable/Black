"""raphael-ma CLI: debates, communities, teams, brain, evolution."""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional

import typer
from rich.console import Console

from raphael.multiagent import __version__
from raphael.multiagent.brain.db import BrainDB
from raphael.multiagent.brain import memory as mem
from raphael.multiagent.brain.evolver import (
    collect_stats,
    evaluate_pending,
    rollback_evolution,
    run_evolver,
)
from raphael.multiagent.config import Config, load_config, write_default_config
from raphael.multiagent.config import load_dotenv
from raphael.multiagent.llm.registry import Registry
from raphael.multiagent.log import configure_logging, get_logger
from raphael.multiagent.harness_provider import build_registry
from raphael.multiagent.paths import config_path, default_home, ensure_home, validate_home_path
from raphael.multiagent.personas import seed_personas
from raphael.multiagent.governance import (
    GovernanceConfigError,
    KillSwitchEngaged,
    UnrestrictedGovernance,
    build_governance,
    get_governance,
)
from raphael.multiagent.ui import banner, error, info, is_json_mode, ok, set_json_mode, summary_table, warn

log = get_logger("cli")

app = typer.Typer(
    name="raphael-ma",
    help="Self-evolving multi-agent CLI: debates, communities, model teams, and a thinking brain.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,
)
brain_app = typer.Typer(help="Inspect and manage the thinking brain.", no_args_is_help=True)
providers_app = typer.Typer(help="Manage LLM providers.", no_args_is_help=True)
evolve_app = typer.Typer(help="Self-evolution (genome) commands.", no_args_is_help=True)
app.add_typer(brain_app, name="brain")
app.add_typer(providers_app, name="providers")
app.add_typer(evolve_app, name="evolve")

gov_app = typer.Typer(help="Governance controls.", no_args_is_help=True)
app.add_typer(gov_app, name="governance")

bench_app = typer.Typer(help="Provider benchmark commands.", no_args_is_help=True)
app.add_typer(bench_app, name="benchmark")

tui_app = typer.Typer(help="Textual mission console (TUI).", no_args_is_help=True)
app.add_typer(tui_app, name="tui")

console = Console()


EXIT_KILL_SWITCH = 3   # governance aborted the session (fail-closed)
EXIT_GOVERNANCE_CONFIG = 4  # unconfigured/misconfigured governance (strict mode)


@app.callback()
def main(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="show debug logging on stderr (or set RAPHAEL_MA_LOG=debug|info|warning|error)",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="machine-readable output: tables as NDJSON on stdout, status to stderr",
    ),
) -> None:
    """raphael-ma — self-evolving multi-agent CLI."""
    load_dotenv(default_home())
    configure_logging(verbose=verbose)
    set_json_mode(json_output)


def _cfg() -> Config:
    return load_config()


@contextmanager
def db_session(cfg: Config) -> Iterator[BrainDB]:
    """Open the brain DB, seed the persona genome, and always close it."""
    db = BrainDB(home=cfg.home)
    try:
        seed_personas(db)
        yield db
    finally:
        db.close()


def _resolve_mode(cfg: Config, live: bool, mock: bool) -> Config:
    """Return a config pinned to the requested mode (never mutates cfg)."""
    if live and mock:
        warn("--live and --mock are mutually exclusive; ignoring both")
        return cfg
    if live:
        return cfg.with_mode("live")
    if mock:
        return cfg.with_mode("mock")
    return cfg




def _host_router_available() -> bool:
    """Presence of Raphael's async provider routing is sufficient to use it."""
    try:
        import orchestrator.providers  # type: ignore[import]
    except Exception:
        return False
    return True


def _registry(cfg):
    # Use raphael-ma's own OpenAI-compatible adapter (cfg.api_key + base_url)
    # instead of the host router, so the user's bound models are actually called
    # and reasoning-only models (nemotron-3.5-lightning, glm-5.3-flash, beam)
    # surface their reply instead of the host router's dead fallback chain.
    return build_registry(
        cfg,
        use_raphael_router=False,
        host_only_live=True,
    )

# ------------------------------------------------------------------- init
@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="overwrite existing config"),
    path: Optional[str] = typer.Option(None, "--path", help="raphael-ma home directory"),
):
    """Create ~/.raphael/ma/config.yaml, the brain DB, and seed the persona genome."""
    try:
        home = validate_home_path(Path(path)) if path else default_home()
    except ValueError as exc:
        error(f"invalid --path: {exc}")
        raise typer.Exit(code=1)
    ensure_home(home)
    cpath = config_path(home)
    if cpath.exists() and not force:
        info(f"config already exists at {cpath} (use --force to reset)")
    else:
        write_default_config(home)
        ok(f"config written → {cpath}")
    cfg = load_config(home)
    try:
        get_governance(cfg)
    except GovernanceConfigError as exc:
        warn(f"existing config: {exc}")
    with db_session(cfg) as db:
        ok(f"brain database ready → {home / 'brain.db'}")
    keys = [p for p in cfg.providers(only_enabled=True) if cfg.api_key(p)]
    if keys:
        ok(f"API keys detected for: {', '.join(keys)} — edit config.yaml to set mode: live")
    else:
        warn("no API keys detected — you are in mock mode (fully functional demo engine)")
    banner("initialized", f"home: {home}")


# ----------------------------------------------------------------- debate
@app.command()
def debate(
    motion: str = typer.Argument(..., help='the motion to debate, e.g. "AI will replace middle management"'),
    rounds: int = typer.Option(None, help="number of rounds (default from config/strategy)"),
    live: bool = typer.Option(False, "--live", help="force live provider mode"),
    mock: bool = typer.Option(False, "--mock", help="force mock provider mode"),
    quiet: bool = typer.Option(False, "-q", "--quiet", help="minimal output"),
    stream: bool = typer.Option(True, "--stream/--no-stream", help="stream tokens as they arrive"),
):
    """PRO vs CON over K rounds, judged and scored; brain learns from it."""
    from raphael.multiagent.orchestrators.debate import run_debate

    cfg = _resolve_mode(_cfg(), live, mock)
    with db_session(cfg) as db:
        try:
            verdict = run_debate(cfg, db, _registry(cfg), motion, rounds=rounds, quiet=quiet, stream=stream)
        except KillSwitchEngaged as exc:
            error(f"governance: {exc}")
            raise typer.Exit(code=EXIT_KILL_SWITCH)
        except GovernanceConfigError as exc:
            error(f"governance: {exc}")
            raise typer.Exit(code=EXIT_GOVERNANCE_CONFIG)
    if verdict and not quiet and not is_json_mode():
        console.print(
            f"\n[bold]Winner:[/bold] {str(verdict.get('winner', 'tie')).upper()}"
        )
    if verdict and is_json_mode():
        print(json.dumps(verdict, ensure_ascii=False))


# -------------------------------------------------------------- community
@app.command()
def community(
    topic: str = typer.Argument(..., help="topic for the round-table"),
    agents: int = typer.Option(None, help="number of agents (2-6)"),
    rounds: int = typer.Option(None, help="rounds of discussion"),
    live: bool = typer.Option(False, "--live"),
    mock: bool = typer.Option(False, "--mock"),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
    stream: bool = typer.Option(True, "--stream/--no-stream"),
):
    """A round-table of specialists, synthesized by a Moderator."""
    from raphael.multiagent.orchestrators.community import run_community

    cfg = _resolve_mode(_cfg(), live, mock)
    with db_session(cfg) as db:
        try:
            run_community(cfg, db, _registry(cfg), topic, n_agents=agents, rounds=rounds, quiet=quiet, stream=stream)
        except KillSwitchEngaged as exc:
            error(f"governance: {exc}")
            raise typer.Exit(code=EXIT_KILL_SWITCH)
        except GovernanceConfigError as exc:
            error(f"governance: {exc}")
            raise typer.Exit(code=EXIT_GOVERNANCE_CONFIG)


# ------------------------------------------------------------------- chat
@app.command()
def chat(
    message: str = typer.Argument(..., help='your message, e.g. "give me a quick risk summary of today"'),
    session: Optional[str] = typer.Option(None, "--session", help="existing chat session id to continue"),
    provider: Optional[str] = typer.Option(None, "--provider", help="pin THIS turn to a provider (needs --model)"),
    model: Optional[str] = typer.Option(None, "--model", help="pin THIS turn to a model id (needs --provider)"),
    force: bool = typer.Option(False, "--force", help="skip the live /models validation of the pinned model id"),
    live: bool = typer.Option(False, "--live"),
    mock: bool = typer.Option(False, "--mock"),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
    stream: bool = typer.Option(True, "--stream/--no-stream"),
):
    """One chat turn with the brain: governed, memory-aware, session-replayable."""
    from raphael.multiagent.orchestrators.chat import run_chat

    cfg = _resolve_mode(_cfg(), live, mock)
    if bool(provider) != bool(model):
        error("--provider and --model must be given together (or neither)")
        raise typer.Exit(code=1)
    if provider and model and cfg.mode == "live" and provider != "mock" and not force:
        # fail fast on ids the provider does not actually serve (EOL etc.)
        from raphael.multiagent.llm.openai_compat import OpenAICompatProvider

        prov = (cfg.providers() or {}).get(provider)
        if prov is None:
            error(f"unknown provider '{provider}'")
            raise typer.Exit(code=1)
        try:
            live_ids = list(
                OpenAICompatProvider(
                    name=provider, base_url=str(prov.get("base_url", "")),
                    api_key=cfg.api_key(provider), timeout=30,
                ).list_models()
            )
        except Exception as exc:
            warn(f"cannot pre-validate against {provider} /models: {str(exc)[:120]}")
            live_ids = None
        if live_ids is not None and model not in live_ids:
            error(
                f"'{model}' is not served by {provider} ({len(live_ids)} live models) — "
                "pick a served id (raphael-ma providers select) or pass --force"
            )
            raise typer.Exit(code=1)
    with db_session(cfg) as db:
        try:
            result = run_chat(
                cfg, db, _registry(cfg), message,
                session=session, quiet=quiet, stream=stream,
                provider_override=provider, model_override=model,
            )
        except KeyError as exc:
            error(str(exc))
            raise typer.Exit(code=1)
        except KillSwitchEngaged as exc:
            error(f"governance: {exc}")
            raise typer.Exit(code=EXIT_KILL_SWITCH)
        except GovernanceConfigError as exc:
            error(f"governance: {exc}")
            raise typer.Exit(code=EXIT_GOVERNANCE_CONFIG)
    if result and is_json_mode():
        print(json.dumps(result, ensure_ascii=False))


# ------------------------------------------------------------------ teams
@app.command()
def teams(
    config: Path = typer.Argument(..., help="teams YAML file (see examples/teams.example.yaml)"),
    mission: Optional[str] = typer.Option(None, help="override the overall mission"),
    integration: Optional[str] = typer.Option(None, "--integration", help="debate | report"),
    parallel: bool = typer.Option(False, "--parallel", help="run team phases concurrently"),
    live: bool = typer.Option(False, "--live"),
    mock: bool = typer.Option(False, "--mock"),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
    stream: bool = typer.Option(True, "--stream/--no-stream"),
):
    """Multiple model-teams, each with its own task; results debated & integrated."""
    from raphael.multiagent.orchestrators.teams import run_teams

    if not config.exists():
        error(f"teams config not found: {config}")
        raise typer.Exit(code=1)
    cfg = _resolve_mode(_cfg(), live, mock)
    with db_session(cfg) as db:
        try:
            run_teams(
                cfg, db, _registry(cfg), config, mission=mission,
                integration_mode=integration, parallel=parallel, quiet=quiet, stream=stream,
            )
        except KillSwitchEngaged as exc:
            error(f"governance: {exc}")
            raise typer.Exit(code=EXIT_KILL_SWITCH)
        except GovernanceConfigError as exc:
            error(f"governance: {exc}")
            raise typer.Exit(code=EXIT_GOVERNANCE_CONFIG)
        except ValueError as exc:
            error(str(exc))
            raise typer.Exit(code=1)


# ------------------------------------------------------------------ brain
@brain_app.command("status")
def brain_status():
    """One-screen overview: sessions, insights, evolutions, genome versions."""
    cfg = _cfg()
    with db_session(cfg) as db:
        stats = collect_stats(db)
        rows = db.one(
            "SELECT (SELECT COUNT(*) FROM sessions) AS sessions,"
            " (SELECT COUNT(*) FROM turns) AS turns,"
            " (SELECT COUNT(*) FROM insights WHERE active=1) AS insights_active,"
            " (SELECT COUNT(*) FROM insights) AS insights_total,"
            " (SELECT COUNT(*) FROM evolutions) AS evolutions,"
            " (SELECT COUNT(*) FROM evolutions WHERE status='active') AS evo_active"
        )
        summary_table(
            "Brain status",
            [
                {"metric": "home", "value": str(cfg.home)},
                {"metric": "mode", "value": cfg.mode},
                {"metric": "sessions", "value": rows["sessions"]},
                {"metric": "journal turns", "value": rows["turns"]},
                {"metric": "insights (active/total)", "value": f"{rows['insights_active']}/{rows['insights_total']}"},
                {"metric": "avg insight confidence", "value": stats["insights"]["avg_confidence"]},
                {"metric": "insights confirmed/contradicted", "value": f"{stats['insights']['confirmed']}/{stats['insights']['contradicted']}"},
                {"metric": "evolutions (total/active)", "value": f"{rows['evolutions']}/{rows['evo_active']}"},
            ],
        )
        pers = db.query(
            "SELECT role, version, note FROM personas WHERE active=1 ORDER BY role"
        )
        summary_table(
            "Genome (active versions)",
            [{"persona": r["role"], "version": r["version"], "origin": (r["note"] or "seed")[:20]} for r in pers],
        )
        evos = db.query(
            "SELECT id, kind, status, reason, created_at FROM evolutions ORDER BY id DESC LIMIT 10"
        )
        if evos:
            summary_table(
                "Recent evolutions",
                [
                    {"id": r["id"], "status": r["status"], "reason": (r["reason"] or "")[:60], "at": r["created_at"]}
                    for r in evos
                ],
            )


@brain_app.command("insights")
def brain_insights(
    active_only: bool = typer.Option(True, "--active/--all"),
    limit: int = typer.Option(20, min=1, max=1000),
):
    """List distilled insights with confidence and validation counts."""
    cfg = _cfg()
    with db_session(cfg) as db:
        where = "WHERE active=1" if active_only else ""
        rows = db.query(
            f"SELECT id, text, confidence, times_used, times_confirmed, times_contradicted,"
            f" active FROM insights {where} ORDER BY confidence DESC LIMIT ?",
            (limit,),
        )
        summary_table(
            "Insights",
            [
                {
                    "id": r["id"], "conf": f"{r['confidence']:.2f}", "used": r["times_used"],
                    "✓/✗": f"{r['times_confirmed']}/{r['times_contradicted']}",
                    "insight": r["text"][:90],
                }
                for r in rows
            ] or [{"id": "—", "conf": "—", "used": "—", "✓/✗": "—", "insight": "(none yet)"}],
        )


@brain_app.command("search")
def brain_search(
    query: str = typer.Argument(...),
    top_k: int = typer.Option(5, "-k", "--top-k", min=1, max=50),
):
    """Semantic search over accumulated insights."""
    cfg = _cfg()
    with db_session(cfg) as db:
        hits = mem.recall(db, query, top_k=top_k, include_inactive=False)
        summary_table(
            f"Search: '{query}'",
            [
                {"id": i, "conf": f"{c:.2f}", "sim": f"{s:.2f}", "insight": t[:90]}
                for i, t, c, s in hits
            ] or [{"id": "—", "conf": "—", "sim": "—", "insight": "(no matches)"}],
        )


@brain_app.command("log")
def brain_log(
    last: int = typer.Option(10, "--last", "-n", min=1, max=1000),
    offset: int = typer.Option(0, "--offset", min=0, help="skip N most recent turns (pagination)"),
    session: Optional[str] = typer.Option(None, "--session"),
):
    """Browse the thinking journal (raw turns)."""
    cfg = _cfg()
    with db_session(cfg) as db:
        if session:
            rows = db.query(
                "SELECT t.*, s.topic FROM turns t JOIN sessions s ON s.id=t.session_id"
                " WHERE t.session_id=? ORDER BY t.seq DESC LIMIT ? OFFSET ?",
                (session, last, offset),
            )
        else:
            rows = db.query(
                "SELECT t.*, s.topic FROM turns t JOIN sessions s ON s.id=t.session_id"
                " ORDER BY t.id DESC LIMIT ? OFFSET ?",
                (last, offset),
            )
        summary_table(
            f"Thinking journal (latest first{f', offset {offset}' if offset else ''})",
            [
                {
                    "session": r["session_id"][:8], "agent": r["agent"],
                    "role": r["role"] or "—", "phase": r["phase"] or "—",
                    "excerpt": (r["content"] or "")[:60].replace("\n", " "),
                }
                for r in rows
            ] or [{"session": "—", "agent": "(empty)", "role": "", "phase": "", "excerpt": ""}],
        )


@brain_app.command("sessions")
def brain_sessions(
    limit: int = typer.Option(10, min=1, max=1000),
    offset: int = typer.Option(0, "--offset", min=0, help="skip N most recent sessions (pagination)"),
):
    """List recorded sessions with verdicts."""
    cfg = _cfg()
    with db_session(cfg) as db:
        # verdict fields are extracted inside SQLite; falls back to a tolerant
        # Python parse only if some legacy row holds malformed JSON
        try:
            rows = db.query(
                "SELECT id, kind, topic, mode, started_at,"
                " json_extract(verdict_json, '$.winner') AS winner,"
                " json_extract(verdict_json, '$.synthesis') AS synthesis"
                " FROM sessions ORDER BY started_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            out = []
            for r in rows:
                v = str(r["winner"] or r["synthesis"] or "")[:40]
                out.append(_session_row(r, v))
        except sqlite3.OperationalError as exc:
            log.warning("json_extract failed (%s); using tolerant parse", exc)
            rows = db.query(
                "SELECT id, kind, topic, mode, started_at, verdict_json"
                " FROM sessions ORDER BY started_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            out = []
            for r in rows:
                v = "—"
                try:
                    parsed = json.loads(r["verdict_json"] or "null")
                    if parsed:
                        v = str(parsed.get("winner") or parsed.get("synthesis") or "—")[:40]
                except (json.JSONDecodeError, TypeError) as exc:
                    log.debug("session %s verdict unparseable: %s", r["id"], exc)
                out.append(_session_row(r, v))
        summary_table("Sessions", out or [{"id": "(none)"}])


def _session_row(r: sqlite3.Row, verdict: str) -> dict:
    return {
        "id": r["id"][:8], "kind": r["kind"], "mode": r["mode"],
        "topic": r["topic"][:40], "verdict": verdict, "at": (r["started_at"] or "")[:16],
    }


@brain_app.command("rollback")
def brain_rollback(evolution_id: int = typer.Argument(...)):
    """Manually revert a genome evolution by its id."""
    cfg = _cfg()
    with db_session(cfg) as db:
        if rollback_evolution(db, evolution_id):
            ok(f"evolution #{evolution_id} reverted; genome restored")
        else:
            error(f"evolution #{evolution_id} not found")


@brain_app.command("reset")
def brain_reset(
    yes: bool = typer.Option(False, "--yes", help="skip confirmation"),
):
    """Wipe the brain (insights, journal, evolutions). Config is kept."""
    cfg = _cfg()
    if not yes:
        warn("this deletes all learned memory. Re-run with --yes to confirm.")
        raise typer.Exit()
    with db_session(cfg) as db:
        db.wipe()
    ok("brain reset to factory state")


@brain_app.command("import")
def brain_import(
    path: Path = typer.Argument(..., help="session export JSON file to import"),
    session_id: Optional[str] = typer.Option(None, "--session-id", help="override the imported session id"),
):
    """Import a previously exported session into the brain.

    The import file should be a JSON object with keys:
      kind, topic, mode, started_at, finished_at, verdict_json, transcript_path,
      turns (list of turn dicts), insights (list of insight dicts).
    """
    import json as _json

    if not path.exists():
        error(f"import file not found: {path}")
        raise typer.Exit(code=1)

    data = _json.loads(path.read_text(encoding="utf-8"))

    cfg = _cfg()
    with db_session(cfg) as db:
        sid = session_id or data.get("session_id") or data.get("id")
        if not sid:
            import uuid as _uuid

            sid = _uuid.uuid4().hex[:12]

        db.execute(
            "INSERT OR IGNORE INTO sessions(id, kind, topic, mode, started_at, finished_at, verdict_json, transcript_path)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (
                sid,
                data.get("kind", "imported"),
                data.get("topic", ""),
                data.get("mode", "mock"),
                data.get("started_at", _dt.datetime.now().isoformat(timespec="seconds")),
                data.get("finished_at"),
                data.get("verdict_json"),
                data.get("transcript_path"),
            ),
        )

        turns = data.get("turns") or []
        for i, t in enumerate(turns, 1):
            db.execute(
                "INSERT INTO turns(session_id, seq, agent, team, role, phase, round, provider, model,"
                " content, latency_ms, ok, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sid, i,
                    t.get("agent", "unknown"),
                    t.get("team"),
                    t.get("role"),
                    t.get("phase"),
                    t.get("round"),
                    t.get("provider"),
                    t.get("model"),
                    t.get("content", ""),
                    t.get("latency_ms", 0),
                    int(t.get("ok", 1)),
                    t.get("created_at", _dt.datetime.now().isoformat(timespec="seconds")),
                ),
            )

        insights = data.get("insights") or []
        for ins in insights:
            from raphael.multiagent.brain import memory as mem

            mem.add_insight(
                db, sid, ins.get("text", ""), float(ins.get("confidence", 0.6))
            )

        db.commit()
        ok(f"imported session {sid[:8]}: {len(turns)} turns, {len(insights)} insights")


# ------------------------------------------------------------------ evolve
@evolve_app.command("run")
def evolve_run(
    dry_run: bool = typer.Option(False, "--dry-run", help="show proposals without applying"),
    live: bool = typer.Option(False, "--live"),
    mock: bool = typer.Option(False, "--mock"),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
):
    """Analyze performance and rewrite the system's own genome."""
    cfg = _resolve_mode(_cfg(), live, mock)
    try:
        gov = get_governance(cfg)
    except GovernanceConfigError as exc:
        error(f"governance: {exc}")
        raise typer.Exit(code=EXIT_GOVERNANCE_CONFIG)
    try:
        gov.check("evolve", {"action": "genome_rewrite", "dry_run": dry_run})
    except KillSwitchEngaged as exc:
        error(f"governance: {exc}")
        raise typer.Exit(code=EXIT_KILL_SWITCH)
    gov.audit({"event": "evolve", "dry_run": dry_run})
    with db_session(cfg) as db:
        run_evolver(cfg, db, _registry(cfg), dry_run=dry_run, quiet=quiet)


@evolve_app.command("evaluate")
def evolve_evaluate():
    """Selection gate: keep or revert pending evolutions."""
    cfg = _cfg()
    with db_session(cfg) as db:
        decided = evaluate_pending(cfg, db)
        if not decided:
            info("no pending evolutions ready for evaluation")


@evolve_app.command("stats")
def evolve_stats():
    """Show the performance stats the evolver sees."""
    cfg = _cfg()
    with db_session(cfg) as db:
        stats = collect_stats(db)
        console.print_json(json.dumps(stats, indent=2))


# -------------------------------------------------------------- providers
@providers_app.command("list")
def providers_list():
    """Show configured providers, endpoints, and key availability."""
    cfg = _cfg()
    rows = []
    for name, prov in cfg.providers().items():
        key = "✓" if cfg.api_key(name) else "—"
        rows.append(
            {
                "provider": name,
                "endpoint": prov.get("base_url", ""),
                "enabled": "yes" if prov.get("enabled") else "no",
                "key_env": prov.get("api_key_env", ""),
                "key": key,
                "models": len(prov.get("models") or []),
            }
        )
    if is_json_mode():
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
        return
    summary_table(f"Providers (mode={cfg.mode})", rows)


@providers_app.command("test")
def providers_test(
    name: Optional[str] = typer.Argument(None, help="test only this provider (default: all enabled)"),
):
    """Health-check enabled providers (GET /models)."""
    cfg = _cfg()
    from raphael.multiagent.llm.openai_compat import OpenAICompatProvider

    targets = list(cfg.providers(only_enabled=True))
    if name:
        if name not in (cfg.providers() or {}):
            error(f"unknown provider '{name}'")
            raise typer.Exit(code=1)
        targets = [name]
    for name in targets:
        prov = cfg.raw["providers"][name]
        p = OpenAICompatProvider(
            name=name,
            base_url=str(prov.get("base_url", "")),
            api_key=cfg.api_key(name),
            timeout=20,
        )
        try:
            models = p.list_models()
            ok(f"{name}: reachable · {len(models)} models")
        except Exception as exc:
            log.warning("provider %s unreachable: %s", name, exc, exc_info=True)
            warn(f"{name}: {str(exc)[:120]}")


@providers_app.command("models")
def providers_models(name: str = typer.Argument(...)):
    """List live models from a provider (GET /v1/models)."""
    cfg = _cfg()
    from raphael.multiagent.llm.openai_compat import OpenAICompatProvider

    prov = (cfg.providers() or {}).get(name)
    if not prov:
        error(f"unknown provider '{name}'")
        raise typer.Exit(code=1)
    p = OpenAICompatProvider(
        name=name,
        base_url=str(prov.get("base_url", "")),
        api_key=cfg.api_key(name),
        timeout=30,
    )
    try:
        models = p.list_models()
        if is_json_mode():
            print(json.dumps({"provider": name, "count": len(models), "models": list(models)}, ensure_ascii=False))
            return
        for m in models:
            console.print(f"  {m}")
        info(f"{len(models)} models · bind roles in config.yaml → roles.<role>.model")
    except Exception as exc:
        log.warning("provider %s model listing failed: %s", name, exc, exc_info=True)
        error(str(exc)[:200])


@providers_app.command("select")
def providers_select(
    provider: str = typer.Argument(..., help="provider name from config.yaml (e.g. nvidia, ollama-cloud, inferx)"),
    model: Optional[str] = typer.Option(None, "--model", help="model id to bind (omit on a TTY to pick from the live list)"),
    role: str = typer.Option("chat", "--role", help='role to bind: a role name, or "all" to rebind every role on this provider'),
    force: bool = typer.Option(False, "--force", help="bind even if the id is not in the provider's live list"),
):
    """Bind a model actually served by the provider's API to a role.

    Fetches the provider's live /models list first, so EOL/decommissioned
    ids fail here instead of producing empty replies at runtime.
    """
    cfg = _cfg()
    from raphael.multiagent.llm.openai_compat import OpenAICompatProvider

    prov = (cfg.providers(only_enabled=True) or {}).get(provider) or (cfg.providers() or {}).get(provider)
    if not prov:
        error(f"unknown provider '{provider}'")
        raise typer.Exit(code=1)

    p = OpenAICompatProvider(
        name=provider,
        base_url=str(prov.get("base_url", "")),
        api_key=cfg.api_key(provider),
        timeout=30,
    )
    try:
        live = list(p.list_models())
    except Exception as exc:
        log.warning("provider %s model listing failed: %s", provider, exc, exc_info=True)
        error(f"cannot reach {provider}: {str(exc)[:180]}")
        raise typer.Exit(code=1)

    chosen = model
    if chosen is None:
        import sys as _sys

        if not _sys.stdin.isatty():
            error(
                "no --model given and stdin is not a TTY — pass --model '<id>' "
                f"(see: raphael-ma providers models {provider})"
            )
            raise typer.Exit(code=1)
        for i, m in enumerate(live, 1):
            console.print(f"  {i:>3}  {m}")
        raw = typer.prompt("number to bind (empty = cancel)", default="", show_default=False)
        if not raw.strip():
            info("selection cancelled — config unchanged")
            return
        try:
            idx = int(raw.strip())
            chosen = live[idx - 1]
        except (ValueError, IndexError):
            error(f"invalid row {raw.strip()!r} — expected 1..{len(live)}")
            raise typer.Exit(code=1)

    if chosen not in live and not force:
        found = [m for m in live if chosen.lower() in m.lower()]
        hint = f" closest: {', '.join(found[:3])}" if found else ""
        error(
            f"'{chosen}' is not served by {provider} ({len(live)} live models){hint} — "
            "pass --force to bind anyway"
        )
        raise typer.Exit(code=1)

    # resolve which roles to write
    if role == "all":
        role_map = {
            r: {"provider": provider, "model": str(chosen)}
            for r, b in (cfg.raw.get("roles") or {}).items()
            if isinstance(b, dict) and b.get("provider") == provider
        }
        if not role_map:
            role_map = {"chat": {"provider": provider, "model": str(chosen)}}
            warn(f"no roles bound to {provider} — creating role 'chat'")
    else:
        role_map = {role: {"provider": provider, "model": str(chosen)}}

    from raphael.multiagent.config import update_role_bindings

    try:
        update_role_bindings(config_path(cfg.home), role_map)
    except FileNotFoundError as exc:
        error(str(exc))
        raise typer.Exit(code=1)

    for r, b in role_map.items():
        ok(f"roles.{r} → {b['provider']}/{b['model']}")
    if is_json_mode():
        print(json.dumps({"provider": provider, "model": chosen, "roles": role_map}, ensure_ascii=False))


# ------------------------------------------------------------------ config
@app.command()
def config(
    reveal: bool = typer.Option(
        False, "--reveal", help="show secret-looking values instead of '***'"
    ),
):
    """Show the effective config and where it lives (secrets masked by default)."""
    cfg = _cfg()
    info(f"path: {config_path(cfg.home)}")
    shown = cfg.raw if reveal else cfg.masked()
    if not reveal:
        info("secret-looking values are masked; use --reveal to show them")
    console.print_json(json.dumps(shown, indent=2, default=str))


@app.command()
def version():
    """Print the version."""
    console.print(f"raphael-ma {__version__}")



@app.command()
def doctor():
    """Diagnose home, config, API-key availability, governance, and brain state."""
    cfg = _cfg()
    info(f"home: {cfg.home}")
    info(f"config: {config_path(cfg.home)}")
    enabled = cfg.providers(only_enabled=True) or {}
    rows = []
    for name, prov in enabled.items():
        rows.append({"provider": name, "endpoint": prov.get("base_url", ""), "key": "?" if cfg.api_key(name) else "?"})
    if rows:
        summary_table("Providers", rows)
    missing = [name for name in enabled if not cfg.api_key(name)]
    if missing:
        warn(f"missing API keys for: {', '.join(missing)} (mock mode will be used)")
    try:
        gov = get_governance(cfg)
        gov.check("doctor", {"home": str(cfg.home)})
        ok("governance: configured and valid")
    except GovernanceConfigError as exc:
        error(str(exc))
        raise typer.Exit(code=4)
    db_path = cfg.home / "brain.db"
    if db_path.exists():
        with db_session(cfg) as db:
            rows = db.one("SELECT COUNT(*) AS sessions FROM sessions")
            ok(f"brain database: present ({rows['sessions']} sessions)")
    else:
        warn(f"brain database not initialized yet ({db_path})")
    ok("doctor complete")


# ------------------------------------------------------------ governance
@gov_app.command("status")
def governance_status():
    """Show current governance configuration and status."""
    cfg = _cfg()
    gov_cfg = cfg.raw.get("governance") or {}
    rows = [
        {"key": "type", "value": gov_cfg.get("type", "null")},
        {"key": "enabled", "value": str(gov_cfg.get("enabled", True))},
        {"key": "audit_path", "value": gov_cfg.get("audit_path", "—")},
        {"key": "kill_switch", "value": gov_cfg.get("kill_switch", "—")},
        {"key": "strict", "value": str(gov_cfg.get("strict", "absent"))},
        {"key": "tool_name", "value": gov_cfg.get("tool_name", "raphael-ma")},
    ]
    summary_table("Governance", rows)
    try:
        gov = get_governance(cfg)
        gov.check("governance_status", {"home": str(cfg.home)})
        stats = getattr(gov, "get_stats", lambda: {})()
        if stats:
            summary_table("Governance stats", [{"k": k, "v": str(v)} for k, v in stats.items()])
        ok("governance: configured and valid")
    except GovernanceConfigError as exc:
        error(str(exc))
        raise typer.Exit(code=4)


@gov_app.command("unrestricted")
def governance_unrestricted(
    enable: bool = typer.Option(True, "--enable/--disable", help="enable or disable unrestricted mode"),
    audit_path: str = typer.Option("logs/redteam.jsonl", "--audit-path", help="audit log path for unrestricted mode"),
    session_tag: str = typer.Option("", "--session-tag", help="optional session tag"),
):
    """Enable unrestricted governance mode for authorized red-team testing.

    WARNING: Only for isolated lab environments with explicit authorization.
    This mode never blocks — it only audits.
    """
    if enable:
        warn("UNRESTRICTED MODE: All safety interlocks disabled")
        warn("Only for authorized lab use. Audit trail is active.")
        if not session_tag:
            session_tag = f"engagement-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        gov = UnrestrictedGovernance(audit_path=audit_path, session_tag=session_tag)
        stats = gov.get_stats()
        summary_table(
            "Unrestricted Governance (active)",
            [
                {"key": k, "value": str(v)}
                for k, v in stats.items()
            ],
        )
        gov.audit({"event": "unrestricted_enabled", "session_tag": session_tag, "audit_path": audit_path})
    else:
        info("Unrestricted mode disabled (not persisted; set governance.type=unrestricted in config.yaml)")


# ------------------------------------------------------------ benchmark
@bench_app.command("run")
def benchmark_run(
    prompt: str = typer.Argument("What are the key principles of secure software development?", help="prompt to benchmark"),
    providers: Optional[str] = typer.Option(None, "--providers", "-p", help="comma-separated provider names (default: all enabled)"),
    model: Optional[str] = typer.Option(None, "--model", help="model id used for every provider (default: each provider's first configured model)"),
    rounds: int = typer.Option(1, "--rounds", "-r", min=1, max=10, help="rounds per provider"),
    live: bool = typer.Option(False, "--live", help="force live provider mode"),
    mock: bool = typer.Option(False, "--mock", help="force mock provider mode"),
    json_out: bool = typer.Option(False, "--json", help="NDJSON output"),
):
    """Benchmark providers on a shared prompt: latency, output length, success."""
    from raphael.multiagent.llm.base import ChatMessage
    from raphael.multiagent.llm.registry import build_provider

    cfg = _resolve_mode(_cfg(), live, mock)
    prov_names = [p.strip() for p in providers.split(",")] if providers else list(cfg.providers(only_enabled=True).keys())
    if not prov_names:
        prov_names = ["mock"]

    results = []
    for name in prov_names:
        model_flag = model
        if not model_flag:
            models_cfg = ((cfg.providers() or {}).get(name) or {}).get("models") or []
            model_flag = str(models_cfg[0]) if models_cfg else None
        if not model_flag:
            results.append({
                "provider": name,
                "round": 0,
                "latency_ms": 0,
                "chars": 0,
                "words": 0,
                "ok": False,
                "error": f"no model bound for {name} — bind one with: raphael-ma providers select {name}",
            })
            continue
        for rnd in range(1, rounds + 1):
            try:
                prov = build_provider(cfg, name)
                t0 = time.time()
                chunks = list(prov.stream_chat(
                    model_flag,
                    [ChatMessage(role="user", content=prompt)],
                    temperature=0.7,
                ))
                elapsed = round((time.time() - t0) * 1000, 1)
                text = "".join(chunks)
                results.append({
                    "provider": name,
                    "round": rnd,
                    "latency_ms": elapsed,
                    "chars": len(text),
                    "words": len(text.split()),
                    "ok": len(text) > 0,
                })
            except Exception as exc:  # provider failure recorded
                results.append({
                    "provider": name,
                    "round": rnd,
                    "latency_ms": 0,
                    "chars": 0,
                    "words": 0,
                    "ok": False,
                    "error": str(exc)[:200],
                })

    if json_out:
        for r in results:
            print(json.dumps(r, default=str))
    else:
        summary_table(
            f"Benchmark · '{prompt[:60]}' · {rounds} round(s)",
            [
                {
                    "provider": r["provider"],
                    "round": r["round"],
                    "latency_ms": r["latency_ms"],
                    "chars": r["chars"],
                    "words": r["words"],
                    "ok": "✓" if r["ok"] else "✗",
                    "error": (r.get("error") or "")[:40],
                }
                for r in results
            ],
        )

    # Aggregate per provider
    agg = {}
    for r in results:
        a = agg.setdefault(r["provider"], {"n": 0, "ok": 0, "lat": 0.0, "chars": 0})
        a["n"] += 1
        if r["ok"]:
            a["ok"] += 1
            a["lat"] += r["latency_ms"]
            a["chars"] += r["chars"]
    if agg:
        rows = []
        for name, a in agg.items():
            avg_lat = round(a["lat"] / max(a["ok"], 1), 1) if a["ok"] else 0
            rows.append({
                "provider": name,
                "runs": a["n"],
                "ok": f"{a['ok']}/{a['n']}",
                "avg_latency_ms": avg_lat,
                "avg_chars": round(a["chars"] / max(a["ok"], 1), 0) if a["ok"] else 0,
            })
        if json_out:
            for r in rows:
                print(json.dumps(r, default=str))
        else:
            summary_table("Benchmark aggregate", rows)


@bench_app.command("providers")
def benchmark_providers():
    """List providers eligible for benchmarking."""
    cfg = _cfg()
    rows = []
    for name in sorted((cfg.providers() or {}).keys()):
        prov = cfg.providers()[name]
        rows.append({
            "provider": name,
            "enabled": "yes" if prov.get("enabled") else "no",
            "key": "✓" if cfg.api_key(name) else "—",
            "models": len(prov.get("models") or []),
        })
    summary_table("Benchmark-eligible providers", rows)


# ------------------------------------------------------------------ tui
@tui_app.command("launch")
def tui_launch(
    home: Optional[str] = typer.Option(None, "--home", help="raphael-ma home directory (default: $RAPHAEL_MA_HOME or ~/.raphael/ma)"),
):
    """Launch the Textual mission console (TUI)."""
    from raphael.multiagent.tui.app import RaphaelTUI
    import sys
    
    # Build sys.argv for the TUI's internal argparse
    tui_argv = ["raphael-ma-tui"]
    if home:
        tui_argv.extend(["--home", home])
    
    # Run the TUI app
    sys.argv = tui_argv
    RaphaelTUI(home=home).run()


if __name__ == "__main__":
    app()
