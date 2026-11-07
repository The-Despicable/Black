"""Debate mode: PRO vs CON over K rounds, then a Judge verdict.

Each side now deliberates (thinking turn) before speaking, and every
speech is delivered with explicit headings (Framework / Arguments /
Rebuttal / Closing) so the transcript is readable instead of a wall of
repetitive prose. The judge quotes specific transcript lines in its
reasoning instead of pattern-matching a canned template.
"""
from __future__ import annotations

from typing import List, Optional

from raphael.multiagent.brain.db import BrainDB
from raphael.multiagent.config import Config
from raphael.multiagent.governance import KillSwitchEngaged
from raphael.multiagent.llm.base import ChatMessage
from raphael.multiagent.llm.registry import Registry
from raphael.multiagent.ui import console, info, summary_table
from raphael.multiagent.orchestrators.base import SessionRunner, emit_event
from raphael.multiagent.orchestrators.base import SessionRunner


def _transcript_block(turns: List[dict]) -> str:
    """Render the debate transcript with round labels for the judge."""
    blocks: List[str] = []
    for t in turns:
        label = f"[{t['agent']} · round {t['round']}]"
        blocks.append(f"{label}\n{t['text']}")
    return "\n\n".join(blocks)


def _thinking_prompt(side: str, motion: str, round_no: int, total_rounds: int, transcript: str) -> str:
    """Deliberation prompt: the model plans its speech before speaking."""
    stance = "PRO (arguing FOR)" if side == "pro" else "CON (arguing AGAINST)"
    closing = (
        "This is the FINAL round: your thinking should focus on closing "
        "points — what survived the exchange and why you win on balance."
        if round_no == total_rounds
        else ""
    )
    return f"""You are DEBATER-{side.upper()}, arguing {stance} on the motion: "{motion}"

Before delivering your speech, think through your position. Produce a
thinking block with exactly these sections:

### Framework
Define the terms of victory for this debate in one sentence.

### Key Arguments
List 2-3 arguments, each as: claim + warrant + concrete example.

### Rebuttal Targets
Identify your opponent's strongest point from the transcript and how
you will neutralize it.

### Closing Points
Name the two points you will defend to the end.

{closing}

Transcript so far:
{transcript}

Reply with ONLY the thinking block, using the section headings above.
No speech yet."""


def _speech_prompt(side: str, motion: str, round_no: int, total_rounds: int, thinking: str, transcript: str) -> str:
    """Speech prompt: deliver a structured speech based on prior thinking."""
    stance = "PRO (arguing FOR)" if side == "pro" else "CON (arguing AGAINST)"
    is_opening = round_no == 1
    is_closing = round_no == total_rounds

    task = (
        "Deliver your opening statement."
        if is_opening
        else "This is the FINAL round: deliver your closing statement."
        if is_closing
        else "Rebut your opponent's strongest point and extend your case."
    )

    return f"""You are DEBATER-{side.upper()}, arguing {stance} on the motion: "{motion}"

TASK: {task}

INSTRUCTIONS:
- Base your speech on the thinking block below (do not repeat it verbatim).
- Structure your speech with these exact headings:
  ### Framework
  ### Arguments
  ### Rebuttal
  ### Closing
- Every argument = claim + warrant + concrete example.
- Attack your opponent's strongest point from the transcript, not their weakest.
- Never concede silently; if a point lands, absorb it and turn it.
- Style: sharp, confident, zero filler. 150-260 words.
- Do NOT include the thinking block in your speech. Deliver only the speech.

THINKING (your prior deliberation — build on it, don't copy it):
{thinking}

TRANSCRIPT SO FAR:
{transcript}

Deliver your speech now with proper headings."""


def _judge_prompt(motion: str, rounds: int, transcript: str) -> str:
    """Judge prompt: score and reason, quoting specific transcript lines."""
    return f"""You are THE JUDGE: impartial, rigorous, allergic to rhetoric without substance.

Motion: "{motion}". You watched {rounds} rounds.

Score both debaters 0-10 and declare a winner based ONLY on argumentation
quality:
- Engagement with opposing argument (did they answer the other side's actual points?)
- Evidence quality (claims backed by warrants and examples?)
- Structure (clear framework, arguments, rebuttal, closing?)
- Adaptability (did they adjust across rounds?)

Transcript:
{transcript}

Reply with ONLY a JSON code block, no prose, no markdown fences:
{{
  "winner": "pro"|"con"|"tie",
  "scores": {{"pro": <0-10>, "con": <0-10>}},
  "reasoning": "<2-3 sentences quoting specific lines from the transcript>",
  "key_moments": ["<short quote>", "<short quote>"]
}}
"""


def _ensure_headings(text: str, is_opening: bool, is_closing: bool) -> str:
    """If a provider ignored the heading instructions, impose minimal structure."""
    has_headings = "### Framework" in text or "### Arguments" in text or "### Rebuttal" in text or "### Closing" in text
    if has_headings:
        return text
    stage = "Opening statement" if is_opening else ("Closing statement" if is_closing else f"Rebuttal — round {is_opening and 1 or 2}")
    return f"### Framework\nThe motion: *{stage}*\n\n### Arguments\n{text.strip()}\n\n### Closing\nOn balance, the case stands.\n"


def _format_turn(
    agent: str, side: str, round_no: int, total_rounds: int, text: str, thinking: Optional[str] = None
) -> str:
    """Wrap a speech with a top-level heading and optional thinking section."""
    stage = "Opening" if round_no == 1 else ("Closing" if round_no == total_rounds else f"Round {round_no}")
    is_opening = round_no == 1
    is_closing = round_no == total_rounds
    body = _ensure_headings(text, is_opening, is_closing)
    parts = [f"## {agent} — {stage}"]
    if thinking:
        parts.append("\n### Thinking (deliberation)\n" + thinking.strip())
    parts.append("\n" + body)
    return "\n".join(parts)


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
                system = runner.persona_system(
                    side, extra_tags=f"[topic:{motion}]" + (f"\n{wisdom}" if wisdom else "")
                )

                # ---- 1) thinking turn (deliberate before speaking) -------
                thinking_history = [
                    ChatMessage(role="system", content=system),
                    ChatMessage(
                        role="user",
                        content=_thinking_prompt(
                            side, motion, rnd, rounds, _transcript_block(turns)
                        ),
                    ),
                ]
                thinking = "".join(
                    provider.stream_chat(
                        binding.model,
                        thinking_history,
                        temperature=0.6,
                        max_tokens=400,
                    )
                )

                # ---- 2) speech turn (structured, headed) -----------------
                history = [
                    ChatMessage(role="system", content=system),
                    ChatMessage(
                        role="user",
                        content=_speech_prompt(
                            side, motion, rnd, rounds, thinking, _transcript_block(turns)
                        ),
                    ),
                ]
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
                    emit_event=False,  # emit below with formatted text
                )
                # wrap with heading + prepend thinking as a compact section
                formatted = _format_turn(agents[side], side, rnd, rounds, text, thinking)
                emit_event({
                    "session_id": runner.session_id,
                    "agent": agents[side],
                    "role": side,
                    "team": None,
                    "phase": "debate",
                    "round": rnd,
                    "provider": binding.provider,
                    "model": binding.model,
                    "latency_ms": runner._last_turn_latency_ms,
                    "ok": True,
                    "text": formatted,
                })
                turns.append(
                    {
                        "agent": agents[side],
                        "side": side,
                        "text": formatted,
                        "round": rnd,
                        "thinking": thinking,
                    }
                )
                runner.add_to_section(agents[side], f"{binding.model} · round {rnd}", formatted)

        # -- judging -------------------------------------------------------
        runner.gate("judgement", topic=motion)
        runner.section("Judgement")
        jb = registry.binding("judge")
        jprovider = registry.provider(jb.provider)
        jmessages = [
            ChatMessage(role="system", content=runner.persona_system("judge")),
            ChatMessage(
                role="user",
                content=_judge_prompt(motion, rounds, _transcript_block(turns)),
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
            max_tokens=900,
        )
        raw_judge = None
        if verdict is None:
            row = db.one(
                "SELECT content FROM turns WHERE session_id=? AND agent='JUDGE' ORDER BY seq DESC LIMIT 1",
                (runner.session_id,),
            )
            raw_judge = (row["content"] if row else "") or ""
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
            "JUDGE",
            f"{jb.model}",
            (
                f"Winner: **{verdict.get('winner', 'tie').upper()}**\n\n"
                f"Scores: PRO {verdict.get('scores', {}).get('pro', '?')} / "
                f"CON {verdict.get('scores', {}).get('con', '?')}\n\n"
                f"{verdict.get('reasoning', '')}"
            ),
        )

        scores = verdict.get("scores") or {}
        for s in ("pro", "con"):
            try:
                runner.record_outcome(
                    agents[s], "agent", float(scores.get(s, 5.0)), {"winner": verdict.get("winner")}
                )
            except (TypeError, ValueError):
                runner.record_outcome(agents[s], "agent", 5.0, {"winner": verdict.get("winner")})

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
                    {
                        "agent": agents[s],
                        "model": registry.binding(s).model,
                        "score": scores.get(s, "?"),
                        "result": "WIN"
                        if verdict.get("winner") == s
                        else ("TIE" if verdict.get("winner") == "tie" else "LOSS"),
                    }
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
