"""Debate mode: PRO vs CON over K rounds, then a Judge verdict."""
from __future__ import annotations

from typing import List, Optional

from raphael.multiagent.brain.db import BrainDB
from raphael.multiagent.config import Config
from raphael.multiagent.governance import KillSwitchEngaged
from raphael.multiagent.llm.base import ChatMessage
from raphael.multiagent.llm.registry import Registry
from raphael.multiagent.ui import console, info, summary_table
from raphael.multiagent.orchestrators.base import SessionRunner


def _transcript_block(turns: List[dict]) -> str:
    return "\n\n".join(f"[{t['agent']}]: {t['text']}" for t in turns)


def run_debate(
    cfg: Config,
    db: BrainDB,
    registry: Registry,
    motion: str,
    rounds: Optional[int] = None,
    quiet: bool = False,
    stream: bool = True,
) -> Optional[dict]:
    rounds = int(rounds or cfg.strategy_param("rounds", 3) or 3)
    runner = SessionRunner(cfg, db, registry, "debate", motion, quiet=quiet, stream=stream)

    roles = ["pro", "con"]
    agents = {"pro": "PRO", "con": "CON"}

    # -- memory injection ----------------------------------------------------
    wisdom, used_ids = runner.memory_system_block(f"debate: {motion}")
    if used_ids:
        from raphael.multiagent.brain import memory as mem

        mem.mark_used(db, used_ids)

    runner.section(f"Debate · {rounds} rounds · motion: {motion}")
    info(f"mode={cfg.mode} · topic='{motion}' · rounds={rounds}")

    turns: List[dict] = []
    try:
        for rnd in range(1, rounds + 1):
            runner.gate("debate_round", round=rnd, rounds=rounds, topic=motion)
            for side in ("pro", "con"):
                binding = registry.binding(side)
                provider = registry.provider(binding.provider)
                stance = "pro" if side == "pro" else "con"
                system = runner.persona_system(
                    side, extra_tags=f"[topic:{motion}]" + (f"\n{wisdom}" if wisdom else "")
                )
                history = [ChatMessage(role="system", content=system)]
                if rnd == 1:
                    history.append(
                        ChatMessage(role="user", content=f'The motion is: "{motion}". Deliver your opening statement.')
                    )
                else:
                    prior = _transcript_block(turns)
                    prompt = (
                        f'The motion is: "{motion}". Round {rnd} of {rounds}. '
                        + ("This is the FINAL round: deliver your closing statement." if rnd == rounds
                           else "Rebut your opponent's strongest point and extend your case.")
                        + f"\n\nTranscript so far:\n{prior}"
                    )
                    history.append(ChatMessage(role="user", content=prompt))
                text = runner.run_turn(
                    agent=agents[side],
                    role=side,
                    provider_name=binding.provider,
                    provider=provider,
                    model=binding.model,
                    messages=history,
                    phase="debate",
                    round_no=rnd,
                    temperature=0.8,
                )
                turns.append({"agent": agents[side], "side": side, "text": text, "round": rnd})
                runner.add_to_section(agents[side], f"{binding.model} · round {rnd}", text)

        # -- judging -------------------------------------------------------
        runner.gate("judgement", topic=motion)
        runner.section("Judgement")
        jb = registry.binding("judge")
        jprovider = registry.provider(jb.provider)
        jmessages = [
            ChatMessage(role="system", content=runner.persona_system("judge")),
            ChatMessage(
                role="user",
                content=(
                    f'Motion: "{motion}". You watched {rounds} rounds. Score both debaters 0-10 '
                    f"and declare a winner.\n\nTRANSCRIPT:\n{_transcript_block(turns)}\n\n"
                    "Respond with ONLY a JSON object, no prose, no markdown fences:\n"
                    '{"winner": "pro"|"con"|"tie", "scores": {"pro": <0-10>, "con": <0-10>}, '
                    '"reasoning": "<one or two sentences>", "key_moments": ["<quote>", ...]}'
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
            phase="judgement",
            max_tokens=700,
        )
        raw_judge = None
        if verdict is None:
            # Surface whatever the judge actually said so the result is
            # human-readable instead of a silent tie.
            row = db.one(
                "SELECT content FROM turns WHERE session_id=? AND agent='JUDGE' ORDER BY seq DESC LIMIT 1",
                (runner.session_id,),
            )
            raw_judge = (row["content"] if row else "") or ""
            # Heuristic fallback: if the reply names a side, honour it.
            low = raw_judge.lower()
            if "pro" in low and "con" not in low:
                winner_guess = "pro"
            elif "con" in low and "pro" not in low:
                winner_guess = "con"
            else:
                winner_guess = "tie"
            verdict = {
                "winner": winner_guess,
                "scores": {"pro": 5.0, "con": 5.0},
                "reasoning": (
                    "Judge output was not parseable as JSON; defaulted. "
                    "Raw judge reply:\n" + (raw_judge[:600] if raw_judge else "(empty)")
                ),
                "key_moments": [],
            }
        runner.add_to_section(
            "JUDGE", f"{jb.model}", (
                f"Winner: **{verdict.get('winner', 'tie').upper()}**\n\n"
                f"Scores: PRO {verdict.get('scores', {}).get('pro', '?')} / "
                f"CON {verdict.get('scores', {}).get('con', '?')}\n\n"
                f"{verdict.get('reasoning', '')}"
            ),
        )

        scores = verdict.get("scores") or {}
        for side in ("pro", "con"):
            try:
                runner.record_outcome(agents[side], "agent", float(scores.get(side, 5.0)), {"winner": verdict.get("winner")})
            except (TypeError, ValueError):
                runner.record_outcome(agents[side], "agent", 5.0, {"winner": verdict.get("winner")})

        if not quiet:
            winner = str(verdict.get("winner", "tie"))
            title = (
                f"Verdict · {winner.upper()} on motion: {motion}"
                if winner == "tie"
                else f"Verdict · {winner.upper()} wins the motion: {motion}"
            )
            summary_table(
                title,
                [
                    {"agent": agents[s], "model": registry.binding(s).model,
                     "score": scores.get(s, "?"), "result": "WIN" if verdict.get("winner") == s else
                     ("TIE" if verdict.get("winner") == "tie" else "LOSS")}
                    for s in ("pro", "con")
                ],
            )

        footer = {
            "motion": motion,
            "rounds": str(rounds),
            "winner": str(verdict.get("winner", "tie")),
            "session_id": runner.session_id,
        }
        runner.finish(verdict=verdict, extra_footer=footer)
    except KillSwitchEngaged as exc:
        runner.abort(str(exc))
        raise

    # -- reflection (Loop 1) --------------------------------------------------
    from raphael.multiagent.brain.reflector import reflect_session

    reflect_session(cfg, db, registry, runner.session_id, runner.kind, motion, turns, quiet=quiet)

    # -- evolution bookkeeping (Loop 2) ---------------------------------------
    from raphael.multiagent.brain.evolver import tick_evolution_counters

    tick_evolution_counters(db)
    runner.close()
    result = dict(verdict or {})
    result.setdefault("winner", "tie")
    result["session_id"] = runner.session_id
    result["motion"] = motion
    return result
