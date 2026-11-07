"""Community mode: an N-persona round-table with a Moderator synthesis."""
from __future__ import annotations

from typing import List, Optional

from raphael.multiagent.brain.db import BrainDB
from raphael.multiagent.config import Config
from raphael.multiagent.governance import KillSwitchEngaged
from raphael.multiagent.llm.base import DEFAULT_SCORE, ChatMessage
from raphael.multiagent.llm.registry import Registry
from raphael.multiagent.personas import get_persona_prompt
from raphael.multiagent.ui import console, info, is_json_mode, summary_table, warn
from raphael.multiagent.orchestrators.base import SessionRunner

COMMUNITY_PERSONAS = ["researcher", "analyst", "critic", "moderator"]
PERSONA_LABELS = {
    "researcher": "RESEARCHER",
    "analyst": "ANALYST",
    "critic": "CRITIC",
    "moderator": "MODERATOR",
}


def _transcript_block(turns: List[dict]) -> str:
    return "\n\n".join(f"[{t['agent']}]: {t['text']}" for t in turns)


def run_community(
    cfg: Config,
    db: BrainDB,
    registry: Registry,
    topic: str,
    n_agents: Optional[int] = None,
    rounds: Optional[int] = None,
    quiet: bool = False,
    stream: bool = True,
) -> Optional[dict]:
    n_agents = int(n_agents or cfg.strategy_param("agents", 4) or 4)
    rounds = int(rounds or cfg.strategy_param("rounds", 2) or 2)
    if n_agents < 2 or n_agents > 6:
        warn(f"--agents {n_agents} outside 2-6; clamping to {max(2, min(6, n_agents))}")
    n_agents = max(2, min(6, n_agents))

    # pick personas for the table (moderator is separate)
    table = COMMUNITY_PERSONAS[: max(2, n_agents - 1)]
    if len(table) < n_agents - 1:
        table = table + [f"critic" for _ in range(n_agents - 1 - len(table))]

    runner = SessionRunner(cfg, db, registry, "community", topic, quiet=quiet, stream=stream)
    wisdom, used_ids = runner.memory_system_block(f"community: {topic}")
    if used_ids:
        from raphael.multiagent.brain import memory as mem

        mem.mark_used(db, used_ids)

    runner.section(f"Round-table · {len(table)} specialists · {rounds} rounds · {topic}")
    info(f"mode={cfg.mode} · participants: {', '.join(PERSONA_LABELS.get(p, p) for p in table)}")

    turns: List[dict] = []
    try:
        for rnd in range(1, rounds + 1):
            runner.gate("community_round", round=rnd, rounds=rounds, topic=topic)
            for p in table:
                binding = registry.binding(p)
                provider = registry.provider(binding.provider)
                system = runner.persona_system(p, extra_tags=f"[topic:{topic}]" + (f"\n{wisdom}" if wisdom else ""))
                prior = _transcript_block(turns)
                if not prior:
                    user = f'The topic for the round-table is: "{topic}". Give your opening contribution.'
                else:
                    user = (
                        f'Topic: "{topic}". Round {rnd} of {rounds}. Respond to what the others said '
                        f"(agree, extend, or push back — cite them by name).\n\nSo far:\n{prior}"
                    )
                messages = [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)]
                label = PERSONA_LABELS.get(p, p)
                text = runner.run_turn(
                    agent=label,
                    role=p,
                    provider_name=binding.provider,
                    provider=provider,
                    model=binding.model,
                    messages=messages,
                    phase="community",
                    round_no=rnd,
                    temperature=0.75,
                )
                turns.append({"agent": label, "persona": p, "text": text, "round": rnd})
                runner.add_to_section(label, f"{binding.model} · round {rnd}", text)

        # -- moderation ------------------------------------------------------
        runner.gate("moderation", topic=topic)
        runner.section("Moderator synthesis")
        mb = registry.binding("moderator")
        mprovider = registry.provider(mb.provider)
        labeled = "\n\n".join(f"[{t['agent']}]: {t['text']}" for t in turns)
        mmessages = [
            ChatMessage(role="system", content=runner.persona_system("moderator")),
            ChatMessage(
                role="user",
                content=f'The round-table topic was: "{topic}". Synthesize the discussion.\n\nTRANSCRIPT:\n{labeled}',
            ),
        ]
        synth = runner.ask_json(
            agent="MODERATOR",
            role="moderator",
            provider=mprovider,
            model=mb.model,
            provider_name=mb.provider,
            messages=mmessages,
            phase="moderation",
            max_tokens=800,
        )
        if synth is None:
            synth = {
                "synthesis": "Moderator output unparseable.",
                "consensus": [],
                "dissent": [],
                "open_questions": [],
                "participant_scores": {},
            }
        if not quiet and not is_json_mode():
            # pretty panel stays on stdout for humans only — json mode gets
            # the structured result instead (printed by the CLI at the end)
            from rich.panel import Panel
            from rich.text import Text

            body = Text()
            body.append(str(synth.get("synthesis", "")), style="white")
            if synth.get("consensus"):
                body.append("\n\nConsensus: ", style="bold green")
                body.append("; ".join(map(str, synth["consensus"])))
            if synth.get("dissent"):
                body.append("\nDissent: ", style="bold yellow")
                body.append("; ".join(map(str, synth["dissent"])))
            if synth.get("open_questions"):
                body.append("\nOpen questions: ", style="bold cyan")
                body.append("; ".join(map(str, synth["open_questions"])))
            console.print(Panel(body, title="[bold]MODERATOR SYNTHESIS[/bold]", border_style="blue"))
        body_md = [
            f"**Synthesis:** {synth.get('synthesis', '')}",
            "",
            "**Consensus:** " + "; ".join(map(str, synth.get("consensus", []) or [])),
            "**Dissent:** " + "; ".join(map(str, synth.get("dissent", []) or [])),
            "**Open questions:** " + "; ".join(map(str, synth.get("open_questions", []) or [])),
        ]
        runner.add_to_section("MODERATOR", mb.model, "\n".join(body_md))

        pscores = synth.get("participant_scores") or {}
        participants: List[dict] = []
        for t in turns:
            try:
                score = float(pscores.get(t["agent"], DEFAULT_SCORE))
            except (TypeError, ValueError):
                score = DEFAULT_SCORE
            runner.record_outcome(t["agent"], "agent", score, {"persona": t["persona"]})
            participants.append({
                "agent": t["agent"], "persona": t["persona"],
                "model": registry.binding(t["persona"]).model,
                "score": score, "turns": sum(1 for x in turns if x["agent"] == t["agent"]),
            })

        if not quiet:
            rows = [
                {"agent": p["agent"], "model": p["model"], "score": p["score"]}
                for p in participants
            ]
            summary_table("Round-table contributions", rows)

        result = {
            "kind": "community",
            "session_id": runner.session_id,
            "topic": topic,
            "participants": participants,
            "synthesis": str(synth.get("synthesis", "")),
            "consensus": list(synth.get("consensus") or []),
            "dissent": list(synth.get("dissent") or []),
            "open_questions": list(synth.get("open_questions") or []),
        }
        runner.finish(
            verdict=result,
            extra_footer={"topic": topic, "participants": ", ".join(t["agent"] for t in turns), "session_id": runner.session_id},
        )
    except KillSwitchEngaged as exc:
        runner.abort(str(exc))
        raise

    from raphael.multiagent.brain.reflector import reflect_session
    from raphael.multiagent.brain.evolver import tick_evolution_counters

    reflect_session(cfg, db, registry, runner.session_id, runner.kind, topic, turns, quiet=quiet)
    tick_evolution_counters(db)
    runner.close()
    return result
