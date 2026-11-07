"""Mock provider: a deterministic-ish, persona-aware fake model.

Every agent persona embeds a machine-readable tag in its system prompt
(``[persona:<role>]`` plus optional ``[stance:...]``/``[task:...]`` markers)
which this engine parses to produce plausible, structured responses. Judge /
reflector / evolver / moderator personas get valid JSON so the full
evolution loop runs offline.
"""
from __future__ import annotations

import json
import random
import re
import time
from typing import Iterator, List, Optional

from raphael.multiagent.llm.base import DEFAULT_SCORE, ChatMessage, Provider

_PERSONA_RE = re.compile(r"\[persona:([a-z_]+)\]", re.IGNORECASE)
_STANCE_RE = re.compile(r"\[stance:([^\]]+)\]", re.IGNORECASE)
_TOPIC_RE = re.compile(r"\[topic:([^\]]+)\]", re.IGNORECASE)


def _extract_tag(messages: List[ChatMessage], regex: re.Pattern) -> Optional[str]:
    for m in messages:
        if m.role == "system":
            found = regex.search(m.content)
            if found:
                return found.group(1).strip()
    return None


def _last_user_text(messages: List[ChatMessage]) -> str:
    for m in reversed(messages):
        if m.role == "user":
            return m.content
    return ""


def _topic(messages: List[ChatMessage], fallback: str = "the topic") -> str:
    tag = _extract_tag(messages, _TOPIC_RE)
    if tag:
        return tag
    text = _last_user_text(messages)
    m = re.search(r'(?:motion|topic|mission|task)\s*(?:is|:)\s*["“]?(.+?)["”]?\s*(?:\n|$)', text, re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip(".")
    return fallback


ARGUMENT_BANK = [
    ("efficiency", "it removes a whole class of coordination overhead that has quietly inflated cost structures for decades"),
    ("incentives", "it realigns incentives with measurable outcomes instead of visibility and politics"),
    ("risk", "it concentrates failure modes in ways that are hard to audit and even harder to reverse"),
    ("second-order effects", "the second-order effects on culture and skill development are routinely underestimated"),
    ("measurability", "the claimed benefits are conveniently hard to measure, while the costs are trivially easy to count"),
    ("precedent", "history shows that structural shifts of this magnitude produce a decade of turbulence before any payoff"),
    ("asymmetry", "the upside is capped and widely shared, but the downside is uncapped and narrowly concentrated"),
    ("optionality", "it preserves optionality: a reversible move now beats a forced move later"),
    ("human judgment", "it quietly assumes away the tacit human judgment that actually holds the system together"),
]

INSIGHT_BANK = [
    "Concrete, quantified claims survive cross-examination far better than qualitative ones.",
    "Arguments that concede a real weakness early are scored higher than blanket denials.",
    "Attacking the strongest opposing point beats attacking the weakest one, every time observed.",
    "Judges consistently reward structure: numbered claims with explicit warrants.",
    "Personas that reference earlier turns by content get judged as more responsive.",
    "Topics about control/autonomy resolve on risk framing, not efficiency framing.",
    "Closing summaries that restate only the strongest two points outperform full restatements.",
    "Splitting a claim into 'what is certain' vs 'what is assumed' exposes hidden weaknesses early.",
]


class MockProvider(Provider):
    """Canned but context-aware responses; streams word-by-word for effect."""

    def __init__(self, seed: Optional[int] = None):
        super().__init__(name="mock", base_url="mock://local", api_key=None, models=["mock-default"])
        self._rng = random.Random(seed if seed is not None else 7)

    # ------------------------------------------------------------------
    def stream_chat(
        self,
        model: str,
        messages: List[ChatMessage],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        text = self._compose(messages, temperature)
        for word in text.split(" "):
            yield word + " "
            time.sleep(0.004)

    def list_models(self) -> List[str]:
        return ["mock-default"]

    # ------------------------------------------------------------------
    def _compose(self, messages: List[ChatMessage], temperature: float) -> str:
        persona = (_extract_tag(messages, _PERSONA_RE) or "generic").lower()
        stance = _extract_tag(messages, _STANCE_RE)
        topic = _topic(messages)
        builder = {
            "pro": self._debater,
            "con": self._debater,
            "judge": self._judge,
            "moderator": self._moderator,
            "reflector": self._reflector,
            "evolver": self._evolver,
            "integrator": self._integrator,
            "researcher": self._researcher,
            "analyst": self._analyst,
            "critic": self._critic,
        }.get(persona, self._generic)
        return builder(persona, stance, topic, messages)

    # ------------------------------------------------------------------
    def _pick_args(self, n: int, exclude: set) -> list:
        pool = [(k, v) for k, v in ARGUMENT_BANK if k not in exclude]
        self._rng.shuffle(pool)
        return pool[:n]

    def _debater(self, persona, stance, topic, messages):
        stance = stance or ("pro" if persona == "pro" else "con")
        favorable = stance.lower() in ("pro", "for", "in favor")
        user_text = _last_user_text(messages)
        turn_no = len([m for m in messages if m.role == "assistant"]) + 1
        opponent_turn = ""
        for m in reversed(messages):
            if m.role == "assistant":
                opponent_turn = m.content
                break

        # ---- structured debate path: thinking block ----------------------
        # Deliberation: strategic plan, distinct headings from the speech.
        if "Reply with ONLY the thinking block" in user_text:
            args = self._pick_args(3, set())
            sign = "strengthens" if favorable else "undermines"
            parts = ["### Framework"]
            parts.append(f"The question turns on whether the benefits are durable and the risks governable.")
            parts.append("\n### Planned Arguments")
            for i, (label, body) in enumerate(args, 1):
                parts.append(f"{i}) {label}: {body}.")
            parts.append("\n### Rebuttal Strategy")
            parts.append("Neutralize the opponent's strongest framing by showing it ignores reversibility and second-order effects.")
            parts.append("\n### Closing Focus")
            parts.append("Defend the strongest two arguments and the framework; concede nothing silently.")
            return "\n".join(parts)

        # ---- structured debate path: headed speech -----------------------
        if "Structure your speech with these exact headings" in user_text:
            # Detect phase from the prompt text, not from message count
            # (history has no assistant messages, so counting them always = 1).
            if "FINAL round" in user_text or "closing statement" in user_text.lower():
                phase = "closing"
            elif "opening statement" in user_text.lower():
                phase = "opening"
            else:
                phase = "rebuttal"
            args = self._pick_args(3 if phase == "opening" else 2, set())
            sign = "strengthens" if favorable else "undermines"
            parts = []
            if phase == "opening":
                parts.append(f"Opening statement on '{topic}': I argue {'for' if favorable else 'against'} this motion.")
            elif phase == "closing":
                parts.append(f"Closing for the {'affirmative' if favorable else 'negative'} on '{topic}'.")
            else:
                parts.append(f"Rebuttal on '{topic}': I answer my opponent's strongest point and extend my case.")
            parts.append("### Framework")
            parts.append(f"The question turns on whether the benefits are durable and the risks governable — applied to '{topic}', this {sign} the motion.")
            parts.append("\n### Arguments")
            for i, (label, body) in enumerate(args, 1):
                parts.append(f"{i}) {label}: {body}.")
            parts.append("\n### Rebuttal")
            if opponent_turn and phase == "rebuttal":
                parts.append(f"Opponent's claim — '{opponent_turn[:100]}.' — overstates certainty and ignores mitigation.")
            elif phase == "opening":
                parts.append("No opposing points on the table yet; pre-empt the risk framing by showing mitigation exists.")
            else:
                parts.append("Their framing ignores reversibility; I show mitigation already exists within open release.")
            parts.append("\n### Closing")
            parts.append("The two points that survive attack: " + "; ".join(f"the {label} argument" for label, _ in args[:2]) + ".")
            parts.append("On balance, the case stands.")
            return " ".join(parts)

        # ---- legacy canned path (fallback) -------------------------------
        context = user_text + "\n" + opponent_turn
        used = {k for k, _ in ARGUMENT_BANK if k in context}
        args = self._pick_args(3 if turn_no == 1 else 2, used)
        sign = "strengthens" if favorable else "undermines"
        parts = []
        if turn_no == 1:
            parts.append(f"Opening statement on '{topic}': I argue {'for' if favorable else 'against'} this motion.")
            parts.append("Framework: the question turns on whether the benefits are durable and the risks governable.")
            for i, (label, body) in enumerate(args, 1):
                parts.append(f"{i}) The {label} argument: {body}. Applied to '{topic}', this {sign} the motion.")
            parts.append("I hold the burden of showing these points survive rebuttal, and I will.")
        elif "closing" in user_text.lower() or turn_no > 3:
            parts.append(f"Closing for the {'affirmative' if favorable else 'negative'} on '{topic}'.")
            parts.append("The two points that survived attack: " + "; ".join(f"the {label} argument" for label, _ in args[:2]) + ".")
            parts.append(f"My opponent's strongest move was invoking risk, but it assumed away mitigation entirely; the clash therefore resolves on {args[0][0]}.")
            parts.append("On balance, the case stands.")
        else:
            parts.append(f"Rebuttal (round {turn_no}) on '{topic}'.")
            if opponent_turn:
                first_claim = opponent_turn.split(".")[0][:120]
                parts.append(f"My opponent's opening claim — '{first_claim}.' — conflates correlation with mechanism.")
            for i, (label, body) in enumerate(args, 1):
                parts.append(f"{i}) Counterpoint on {label}: {body}.")
            parts.append("I turn their framing: what they call prudence is simply status-quo bias.")
        return " ".join(parts)

    def _judge(self, persona, stance, topic, messages):
        transcript = _last_user_text(messages)
        team_leads = re.findall(r"\[([a-z0-9_-]+)-LEAD\]", transcript, re.IGNORECASE)
        if team_leads:
            # cross-team debate: score the teams
            uniq = sorted(set(t.lower() for t in team_leads))
            scores = {t: round(6.8 + self._rng.random() * 2.4, 1) for t in uniq}
            best = max(scores, key=lambda k: scores[k])
            verdict = {
                "winner": best,
                "scores": scores,
                "reasoning": (
                    f"Each lead defended their team's result on '{topic}'. The stronger case paired "
                    "claims with explicit rollback triggers; the weaker one leaned on projections."
                ),
                "key_moments": [
                    f"{uniq[0]}'s framing set the terms of the exchange.",
                    f"{uniq[-1]}'s counterattack on scope assumptions landed hardest.",
                ],
            }
            return "```json\n" + json.dumps(verdict, indent=2) + "\n```"

        # Extract one signature line from each side for the reasoning.
        # Transcript format: "[PRO · round N]\n<speech text>"
        # Skip headings, rules, and thinking-block noise to find real speech.
        SKIP_PREFIXES = ("###", "##", "---")
        pro_quote = "structured opening"
        con_quote = "structured rebuttal"
        current_agent = None
        for line in transcript.split("\n"):
            stripped = line.strip()
            m = re.match(r"\[(PRO|CON) · round \d+\]", stripped)
            if m:
                current_agent = m.group(1)
                continue
            if not stripped or stripped.startswith(SKIP_PREFIXES):
                continue
            if current_agent == "PRO":
                pro_quote = stripped[:90]
                current_agent = None
            elif current_agent == "CON":
                con_quote = stripped[:90]
                current_agent = None

        # Deterministic but varied scoring based on transcript content.
        pro_len = 1 if pro_quote != "structured opening" else 0
        con_len = 1 if con_quote != "structured rebuttal" else 0
        pro_score = round(7.0 + min(pro_len * 0.4, 2.0), 1)
        con_score = round(7.0 + min(con_len * 0.4, 2.0), 1)
        if abs(pro_score - con_score) < 0.3:
            winner = "tie"
        else:
            winner = "pro" if pro_score > con_score else "con"

        verdict = {
            "winner": winner,
            "scores": {"pro": pro_score, "con": con_score},
            "reasoning": (
                f"PRO opened with: \"{pro_quote}...\" CON answered with: \"{con_quote}...\". "
                f"The side that grounded claims in the transcript's structure and answered the "
                f"opponent's specific points took the decision."
            ),
            "key_moments": [
                f"PRO's framing — '{pro_quote[:70]}...'",
                f"CON's rebuttal — '{con_quote[:70]}...'",
            ],
        }
        return "```json\n" + json.dumps(verdict, indent=2) + "\n```"

    def _moderator(self, persona, stance, topic, messages):
        transcript = _last_user_text(messages)
        names = sorted(set(re.findall(r"\[([A-Z][A-Za-z0-9 _-]{1,24})\]", transcript))) or ["Agent 1", "Agent 2"]
        synth = {
            "synthesis": f"The round-table on '{topic}' converged on more than expected.",
            "consensus": [
                f"{names[0]} and others agreed the core question is governance, not capability.",
                "All participants treated measurable outcomes as the deciding criterion.",
            ],
            "dissent": [
                f"{names[-1] if len(names) > 1 else names[0]} maintained that transition costs dominate for at least a decade.",
            ],
            "open_questions": ["Who audits the auditors once the system is deployed?"],
            "participant_scores": {n: round(DEFAULT_SCORE + self._rng.random() * 3, 1) for n in names},
        }
        return "```json\n" + json.dumps(synth, indent=2) + "\n```"

    def _reflector(self, persona, stance, topic, messages):
        user_text = _last_user_text(messages)
        past_ids = [int(x) for x in re.findall(r"\[(\d+)\]", user_text)]
        # exclude insights that already exist verbatim (dedup upstream too)
        existing = set(re.findall(r"^- \[\d+\] (.+?) \(confidence", user_text, re.MULTILINE))
        pool = [p for p in INSIGHT_BANK if p not in existing] or INSIGHT_BANK
        picks = self._rng.sample(pool, min(3, len(pool)))
        confirmations = []
        if past_ids:
            n = min(len(past_ids), self._rng.randrange(0, 3))
            for iid in self._rng.sample(past_ids, n):
                rel = self._rng.choice(["confirmed", "confirmed", "contradicted"])
                confirmations.append(
                    {"insight_id": iid, "relation": rel,
                     "why": f"this session's exchange on '{topic}' {rel} it."}
                )
        payload = {
            "insights": [
                {"text": p, "confidence": round(0.55 + self._rng.random() * 0.2, 2)} for p in picks
            ],
            "confirmations": confirmations,
        }
        return "```json\n" + json.dumps(payload, indent=2) + "\n```"

    def _evolver(self, persona, stance, topic, messages):
        edits = [
            {
                "target": "persona:pro",
                "field": "prompt",
                "action": "append",
                "value": "\nDirective 7: quantify at least one claim per turn; judges reward numbers.",
                "reason": "PRO's mean judge score trails CON; quantified claims correlate with wins.",
            },
            {
                "target": "persona:con",
                "field": "prompt",
                "action": "append",
                "value": "\nDirective 5: pre-empt the strongest opposing argument before it is made.",
                "reason": "CON wins on rebuttal but loses points for being reactive rather than anticipatory.",
            },
        ]
        return "```json\n" + json.dumps({"edits": edits}, indent=2) + "\n```"

    def _integrator(self, persona, stance, topic, messages):
        text = _last_user_text(messages)
        teams = re.findall(r"## (TEAM [^\n]+)", text) or ["Team A", "Team B"]
        lines = [f"Integrated result for '{topic}'.", ""]
        lines.append("### What each team contributed")
        for t in teams:
            lines.append(f"- {t}: strongest element retained — its core recommendation, restated compactly.")
        lines.append("")
        lines.append("### Points of conflict resolved")
        lines.append("- Where teams disagreed on sequencing, the earlier milestone wins; both plans assumed the same end-state.")
        lines.append("- Cost estimates differed by scope boundary, not methodology; the tighter scope is adopted.")
        lines.append("")
        lines.append("### Integrated plan")
        lines.append("1. Adopt the shared goal all teams assumed implicitly.")
        lines.append("2. Sequence the work following the lower-risk plan, borrow the measurement scheme from the other team.")
        lines.append("3. Revisit at the first checkpoint with real data instead of projections.")
        return "\n".join(lines)

    def _researcher(self, persona, stance, topic, messages):
        variant = self._rng.randrange(3)
        openers = [
            f"Research notes on '{topic}': three findings matter.",
            f"Evidence review for '{topic}', ordered by strength:",
            f"What the literature actually says about '{topic}':",
        ]
        middles = [
            "First, the strongest evidence base concerns adjacent domains — the direct studies are thin. "
            "Second, terminology splits into two camps; I flag which terms I use. "
            "Third, there is one well-documented counterexample that any serious position must address.",
            "First, effect sizes are smaller than the headlines suggest. "
            "Second, the best-run studies disagree on measurement, not direction. "
            "Third, nobody has replicated the flagship result under field conditions.",
            "First, most claims trace back to two primary sources. "
            "Second, the negative results are unpublished and therefore invisible. "
            "Third, one recent replication inverted the sign of the effect.",
        ]
        return f"{openers[variant]} {middles[variant]}"

    def _analyst(self, persona, stance, topic, messages):
        variant = self._rng.randrange(3)
        openers = [
            f"Analysis of '{topic}': decomposing into mechanism, cost, and reversibility.",
            f"Structured take on '{topic}' — constraints first:",
            f"Decomposition of '{topic}' by decision-relevant axis:",
        ]
        middles = [
            "Mechanism: plausible but with one unproven link. Cost: front-loaded, then declining. "
            "Reversibility: high if staged, low if done in one move — so staging is the load-bearing recommendation.",
            "Hard constraint: the timeline is fixed, so anything not decomposable into two-week slices is out. "
            "Soft constraint: team bandwidth. Recommendation: cut scope, not quality.",
            "Upside case: compounding gains after initial friction. Downside case: lock-in before validation. "
            "Recommendation: run the reversible version first, commit only after the first checkpoint.",
        ]
        return f"{openers[variant]} {middles[variant]}"

    def _critic(self, persona, stance, topic, messages):
        prior = _last_user_text(messages)
        weak = prior.split(".")[0][:100] if prior else "the proposal"
        variant = self._rng.randrange(3)
        frames = [
            f"Critique: the claim that '{weak}.' rests on an unstated assumption — that conditions stay stable.",
            f"Critique: '{weak}.' was asserted, not derived; the mechanism is doing no work.",
            f"Critique: '{weak}.' survives only in the absence of adversaries.",
        ]
        return (
            f"{frames[variant]} "
            "Two failure modes are unaddressed: adversarial adaptation, and metric gaming. "
            "The proposal is salvageable if it adds an explicit rollback trigger."
        )

    def _generic(self, persona, stance, topic, messages):
        return (
            f"[{persona}] Considering '{topic}': I weigh the evidence, note the key trade-off, "
            "and land on a measured position with one caveat about scale."
        )
