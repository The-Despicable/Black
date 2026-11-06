"""Teams mode.

Each team = several models with its own task. Phase 1: intra-team
collaboration (members discuss the team task, the lead synthesizes a TEAM
RESULT). Phase 2: integration, either:
  - report:   every team result is handed to the Integrator directly
  - debate:   team leads debate each other's results (judge scores them),
              THEN the Integrator merges the best of both
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from raphael.multiagent.brain.db import BrainDB
from raphael.multiagent.config import Config
from raphael.multiagent.governance import KillSwitchEngaged
from raphael.multiagent.llm.base import ChatMessage
from raphael.multiagent.llm.registry import Registry
from raphael.multiagent.personas import DEFAULT_GENOME, get_persona_prompt
from raphael.multiagent.ui import error, info, summary_table, warn
from raphael.multiagent.orchestrators.base import SessionRunner

KNOWN_PERSONAS = set(DEFAULT_GENOME.keys())
VALID_INTEGRATION_MODES = {"debate", "report"}


class TeamSpec:
    def __init__(self, name: str, task: str, members: List[dict]):
        self.name = name
        self.task = task
        self.members = members  # [{name, persona, provider, model}]

    @property
    def label(self) -> str:
        return f"TEAM {self.name.upper()}"

    def lead(self) -> dict:
        for m in self.members:
            if m.get("lead"):
                return m
        return self.members[0]


def load_team_config(path: Path) -> dict:
    data = yaml.safe_load(Path(path).read_text()) or {}
    if not data.get("teams"):
        raise ValueError("teams config must define a 'teams:' mapping with at least one team")
    for name, spec in data["teams"].items():
        if not spec.get("members"):
            raise ValueError(f"team '{name}' has no members")
        for m in spec["members"]:
            if "name" not in m:
                raise ValueError(f"team '{name}' has a member without a name")
    return data


def _validate_members(cfg: Config, spec: dict) -> List[dict]:
    """Fill defaults for provider/model/persona on each member."""
    known_providers = set(cfg.providers().keys()) | {"mock"}
    members = []
    for m in spec.get("members", []):
        persona = m.get("persona")
        if persona and persona not in KNOWN_PERSONAS:
            warn(f"persona '{persona}' unknown; role routing will still be attempted")
        role_for_defaults = persona if persona in KNOWN_PERSONAS else "analyst"
        binding = cfg.role_binding(role_for_defaults)
        provider = m.get("provider") or binding.provider
        if provider not in known_providers:
            warn(
                f"member '{m.get('name', '?')}' references provider '{provider}' which is not "
                f"defined in config.yaml (known: {', '.join(sorted(known_providers))})"
            )
        members.append(
            {
                "name": str(m["name"]),
                "persona": persona or "analyst",
                "provider": provider,
                "model": m.get("model") or binding.model,
                "lead": bool(m.get("lead", False)),
                "prompt": m.get("prompt"),  # optional fully-custom system prompt
            }
        )
    if not any(mm["lead"] for mm in members):
        members[0]["lead"] = True
    return members


def _member_system(runner: SessionRunner, member: dict, team: TeamSpec) -> str:
    if member.get("prompt"):
        return f"[persona:{member['persona']}]\n[topic:{team.task}]\n{member['prompt']}"
    base = get_persona_prompt(runner.db, member["persona"])
    return (
        f"{base}\n[topic:{team.task}]\nYou are '{member['name']}' on {team.label}. "
        f"Your team's task: {team.task}"
    )


def _run_team_phase(
    runner: SessionRunner,
    cfg: Config,
    registry: Registry,
    team: TeamSpec,
    members: List[dict],
    internal_rounds: int,
) -> dict:
    """Intra-team collaboration; returns {'lead', 'result', 'turns'}."""
    runner.gate("team_phase", team=team.name, task=team.task[:80])
    runner.section(f"{team.label} · task: {team.task}")
    wisdom, used_ids = runner.memory_system_block(f"team {team.name}: {team.task}")
    if used_ids:
        from raphael.multiagent.brain import memory as mem

        mem.mark_used(runner.db, used_ids)

    turns: List[dict] = []
    for rnd in range(1, internal_rounds + 1):
        for m in members:
            provider = registry.provider(m["provider"])
            system = _member_system(runner, m, team) + (f"\n{wisdom}" if wisdom else "")
            prior = "\n\n".join(f"[{t['agent']}]: {t['text']}" for t in turns)
            if prior:
                user = (
                    f"Team task: {team.task}. Round {rnd}. Build on or challenge teammates' points:\n{prior}"
                )
            else:
                user = f"Team task: {team.task}. Make your opening contribution to the team effort."
            messages = [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)]
            text = runner.run_turn(
                agent=m["name"],
                role=m["persona"],
                provider_name=m["provider"],
                provider=provider,
                model=m["model"],
                messages=messages,
                phase="team",
                round_no=rnd,
                team=team.name,
                temperature=0.7,
            )
            turns.append({"agent": m["name"], "text": text})
            runner.add_to_section(m["name"], f"{m['model']} · {m['provider']} · round {rnd}", text)

    # lead synthesizes the TEAM RESULT
    lead_member = next(mm for mm in members if mm["lead"]) or members[0]
    provider = registry.provider(lead_member["provider"])
    system = (
        get_persona_prompt(runner.db, lead_member["persona"])
        + f"\n[topic:{team.task}]\nYou are '{lead_member['name']}', the LEAD of {team.label}. "
          f"Synthesize your team's work on the task: {team.task} into a single TEAM RESULT "
          f"(markdown, <=300 words: findings, recommendation, confidence + risks)."
    )
    prior = "\n\n".join(f"[{t['agent']}]: {t['text']}" for t in turns)
    messages = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=f"Team transcript:\n{prior}"),
    ]
    result = runner.run_turn(
        agent=f"{lead_member['name']} (LEAD)",
        role=lead_member["persona"],
        provider_name=lead_member["provider"],
        provider=provider,
        model=lead_member["model"],
        messages=messages,
        phase="team-synthesis",
        team=team.name,
        temperature=0.4,
    )
    runner.add_to_section(f"{lead_member['name']} (LEAD)", f"TEAM RESULT · {lead_member['model']}", result)
    return {"team": team, "members": members, "result": result, "turns": turns, "lead": lead_member}


def run_teams(
    cfg: Config,
    db: BrainDB,
    registry: Registry,
    config_path: Path,
    mission: Optional[str] = None,
    integration_mode: Optional[str] = None,
    parallel: bool = False,
    quiet: bool = False,
    stream: bool = True,
) -> Optional[dict]:
    data = load_team_config(config_path)
    mission = mission or data.get("mission") or "collaborative multi-team task"
    integration_mode = (integration_mode or (data.get("integration", {}) or {}).get("mode", "debate")).strip().lower()
    if integration_mode not in VALID_INTEGRATION_MODES:
        raise ValueError(
            f"integration mode must be one of {sorted(VALID_INTEGRATION_MODES)}, got '{integration_mode}'"
        )
    integration_rounds = int((data.get("integration", {}) or {}).get("rounds", 2))
    internal_rounds = int(cfg.strategy_param("internal_rounds", 1) or 1)

    teams: List[TeamSpec] = []
    for name, spec in data["teams"].items():
        members = _validate_members(cfg, spec)
        teams.append(TeamSpec(str(name), str(spec.get("task", mission)), members))

    runner = SessionRunner(cfg, db, registry, "teams", mission, quiet=quiet, stream=stream)
    info(
        f"mode={cfg.mode} · teams={len(teams)} · integration={integration_mode} · "
        f"parallel={parallel}"
    )

    try:
        # ---------------- Phase 1: each team does its own task --------------
        results: List[dict] = []
        if parallel and len(teams) > 1 and stream and not quiet:
            warn("parallel execution buffers team output; panels print as each team finishes")
        if parallel and len(teams) > 1:
            # run teams concurrently; print happens as futures complete (buffered turns)
            with ThreadPoolExecutor(max_workers=len(teams)) as pool:
                futures = {
                    pool.submit(
                        _run_team_phase, runner, cfg, registry, t,
                        _validate_members(cfg, {"members": [dict(m) for m in t.members]}),
                        internal_rounds,
                    ): t
                    for t in teams
                }
                for fut in futures:
                    results.append(fut.result())
        else:
            for t in teams:
                members = [m for m in t.members]
                results.append(_run_team_phase(runner, cfg, registry, t, members, internal_rounds))

        # ---------------- Phase 2: integration --------------------------------
        runner.gate("integration", mode=integration_mode)
        runner.section(f"Integration ({integration_mode})")
        ib = registry.binding("integrator")
        iprovider = registry.provider(ib.provider)

        if integration_mode == "debate" and len(results) >= 2:
            # leads debate each other's team results
            debate_turns: List[dict] = []
            for rnd in range(1, integration_rounds + 1):
                runner.gate("integration_debate", round=rnd, rounds=integration_rounds)
                for i, res in enumerate(results):
                    other = results[(i + 1) % len(results)]
                    lead = res["lead"]
                    provider = registry.provider(lead["provider"])
                    system = (
                        get_persona_prompt(runner.db, lead["persona"])
                        + f"\n[topic:{mission}]\nYou are '{lead['name']}', LEAD of {res['team'].label}. "
                          f"Overall mission: {mission}. Your team produced a result; another team's "
                          f"result conflicts with yours on points. Defend yours, attack theirs on merits."
                    )
                    prior = "\n\n".join(f"[{t['agent']}]: {t['text']}" for t in debate_turns)
                    user = (
                        f"Round {rnd} of the cross-team debate.\n\n"
                        f"## {res['team'].label} RESULT (yours)\n{res['result']}\n\n"
                        f"## {other['team'].label} RESULT (theirs)\n{other['result']}\n"
                        + (f"\nDebate so far:\n{prior}" if prior else "")
                    )
                    text = runner.run_turn(
                        agent=f"{res['team'].name}-LEAD",
                        role=lead["persona"],
                        provider_name=lead["provider"],
                        provider=provider,
                        model=lead["model"],
                        messages=[ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)],
                        phase="integration",
                        round_no=rnd,
                        team=res["team"].name,
                        temperature=0.75,
                    )
                    debate_turns.append({"agent": f"{res['team'].name}-LEAD", "text": text})
                    runner.add_to_section(f"{res['team'].name}-LEAD", f"cross-team debate · round {rnd}", text)

            # judge scores the teams
            jb = registry.binding("judge")
            jprovider = registry.provider(jb.provider)
            labeled = "\n\n".join(f"[{t['agent']}]: {t['text']}" for t in debate_turns)
            team_ids = {f"{r['team'].name}-LEAD": r["team"].name for r in results}
            jmessages = [
                ChatMessage(role="system", content=runner.persona_system("judge")),
                ChatMessage(
                    role="user",
                    content=(
                        f"Cross-team debate for mission: '{mission}'. Each LEAD argued for their team's result. "
                        f"Score each TEAM 0-10 and pick the strongest result. Reply ONLY as JSON:\n"
                        '```json\n{"winner": "<team name>", "scores": {"<team name>": 0-10, ...}, '
                        '"reasoning": "...", "key_moments": ["..."]}\n```\n\n'
                        f"TRANSCRIPT:\n{labeled}"
                    ),
                ),
            ]
            verdict = runner.ask_json(
                agent="JUDGE",
                role="judge",
                provider=jprovider,
                model=jb.model,
                provider_name=jb.provider,
                messages=jmessages,
                phase="integration-judge",
                max_tokens=700,
            ) or {"winner": "", "scores": {}, "reasoning": "judge unparseable", "key_moments": []}
            for team_name, score in (verdict.get("scores") or {}).items():
                try:
                    runner.record_outcome(f"TEAM {team_name}", "team", float(score), {"winner": verdict.get("winner")})
                except (TypeError, ValueError):
                    pass
            if not quiet:
                summary_table(
                    f"Cross-team debate verdict · strongest: {verdict.get('winner', '?')}",
                    [
                        {"team": k, "score": v}
                        for k, v in (verdict.get("scores") or {}).items()
                    ] or [{"team": "(no scores)", "score": "—"}],
                )
            runner.add_to_section(
                "JUDGE", f"{jb.model}",
                f"Strongest team result: **{verdict.get('winner', '?')}**\n\n"
                + "; ".join(f"{k}: {v}" for k, v in (verdict.get("scores") or {}).items())
                + f"\n\n{verdict.get('reasoning', '')}",
            )
        else:
            verdict = None

        # final integration deliverable
        team_results_md = "\n\n".join(
            f"## TEAM {r['team'].name.upper()} · task: {r['team'].task}\n{r['result']}" for r in results
        )
        debate_note = ""
        if verdict:
            debate_note = (
                f"\n\nThe Judge scored the cross-team debate: {verdict.get('scores')} "
                f"(strongest: {verdict.get('winner')}). Weigh accordingly."
            )
        imessages = [
            ChatMessage(role="system", content=runner.persona_system("integrator", extra_tags=f"[topic:{mission}]")),
            ChatMessage(
                role="user",
                content=(
                    f"Overall mission: {mission}. Integrate the team results below into one deliverable."
                    f"{debate_note}\n\n{team_results_md}"
                ),
            ),
        ]
        integrated = runner.run_turn(
            agent="INTEGRATOR",
            role="integrator",
            provider_name=ib.provider,
            provider=iprovider,
            model=ib.model,
            messages=imessages,
            phase="integration",
            temperature=0.4,
            max_tokens=1600,
        )
        runner.add_to_section("INTEGRATOR", f"{ib.model} · final deliverable", integrated)

        if not quiet:
            summary_table(
                "Teams",
                [
                    {"team": r["team"].name, "members": ", ".join(m["name"] for m in r["members"]),
                     "models": ", ".join(m["model"] for m in r["members"])}
                    for r in results
                ],
            )

        runner.finish(
            verdict=verdict or {"integration": "report"},
            extra_footer={
                "mission": mission,
                "teams": ", ".join(r["team"].name for r in results),
                "integration_mode": integration_mode,
                "session_id": runner.session_id,
            },
        )
    except KillSwitchEngaged as exc:
        runner.abort(str(exc))
        raise


    all_turns = [t for r in results for t in r["turns"]]
    from raphael.multiagent.brain.reflector import reflect_session
    from raphael.multiagent.brain.evolver import tick_evolution_counters

    reflect_session(cfg, db, registry, runner.session_id, runner.kind, mission, all_turns, quiet=quiet)
    tick_evolution_counters(db)
    runner.close()
    return verdict or {"integration": "report", "deliverable": integrated[:200]}
