"""The triage module: LM judgment inside a mechanically enforced envelope.

The shape being demonstrated is that `forward()` has three kinds of statement in it and
they are not interchangeable:

  * calls into `pycode` -- the campaign's MECHANICAL blocks, already written as code.
    These decide; they are never asked.
  * calls into a DSPy predictor -- the places where the campaign genuinely needs a
    judgment that no predicate can make.
  * guards between the two, which refuse an LM conclusion that a mechanical rule does
    not license. The guards are fail-closed in the same sense `submit_gate()` is: the
    failure path returns a refusal, not a default.

`pycode.roster.roster_pass` is imported rather than restated, exactly as the campaign
requires of the sheet writer and the pre-order re-check. If the five criteria ever move,
they move in one place and this module follows.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

import dspy

from pycode.roster import roster_pass, timeout_for

from .lookups import REQUIRED_INDEXES, Logbook, make_tools
from .signatures import (
    DiagnoseBringupFailure,
    JustifyDrop,
    ProposeNextAttempt,
    TriageUnguarded,
)

# st-260: a retry must differ from the prior attempt "in a way you can name". Two
# phrasings this close are the same attempt wearing a different sentence.
RESTATEMENT_RATIO = 0.80


@dataclass
class BringupEvidence:
    """One canary result, in the terms st-230's five PASS criteria are written in."""

    recipe_name: str
    pinned_source: str
    invocation: str
    roster_role: str
    container_builds: bool
    weights_checksum_matches: bool
    end_to_end_exit_code: int
    n_designs: int
    parsed_structures: int
    sequences_emitted: int
    stderr_tail: str = ""
    benchmarked_p90_s: float = 300.0
    prior_attempts: list[str] = field(default_factory=list)

    def criteria(self) -> dict[str, object]:
        return {
            "container_builds": self.container_builds,
            "weights_checksum_matches": self.weights_checksum_matches,
            "end_to_end_exit_code": self.end_to_end_exit_code,
            "n_designs": self.n_designs,
            "parsed_structures": self.parsed_structures,
            "sequences_emitted": self.sequences_emitted,
        }

    def failed_criteria(self) -> list[str]:
        named = [
            ("builds", self.container_builds),
            ("weights_checksum", self.weights_checksum_matches),
            ("exit_zero", self.end_to_end_exit_code == 0 and 2 <= self.n_designs <= 4),
            ("structures_parse", self.parsed_structures >= self.n_designs),
            ("adapter_consumes", self.sequences_emitted >= 1),
        ]
        return [name for name, ok in named if not ok]


def is_restatement(candidate: str, priors: list[str]) -> bool:
    """st-260, mechanically: is this difference actually a difference?"""
    c = candidate.strip().lower()
    if not c:
        return True
    return any(
        difflib.SequenceMatcher(None, c, p.strip().lower()).ratio() >= RESTATEMENT_RATIO
        for p in priors
    )


class RosterTriage(dspy.Module):
    """Triage one failed bring-up into DISPATCH, RETRY, DROP, or BLOCKED."""

    def __init__(self, max_iters: int = 6, refine_n: int = 3):
        super().__init__()
        self.log = Logbook()
        self.diagnose = dspy.Refine(
            dspy.ReAct(DiagnoseBringupFailure, tools=make_tools(self.log),
                       max_iters=max_iters),
            N=refine_n,
            reward_fn=self._diagnosis_reward,
            threshold=1.0,
        )
        self.propose = dspy.ChainOfThought(ProposeNextAttempt)
        self.justify = dspy.ChainOfThought(JustifyDrop)

    # ── the reward that st-216 and st-250 impose on a diagnosis ───────────────────────

    def _diagnosis_reward(self, _inputs: dict, pred: dspy.Prediction) -> float:
        """Not a preference. A conclusion the campaign does not license scores zero.

        Passing this to `dspy.Refine` is the honest encoding: the model gets another
        attempt with its own failure in view, and the caller still refuses to emit an
        unlicensed conclusion if it never gets there.
        """
        cause = getattr(pred, "cause", "")
        if cause == "UNAVAILABLE" and not self.log.satisfies_unavailability_rule():
            return 0.0
        if cause in ("UPSTREAM_BROKEN", "KNOWN_LIMITATION") and \
                not self.log.consulted_method_sources():
            return 0.0
        return 1.0

    # ── forward ───────────────────────────────────────────────────────────────────────

    def forward(self, evidence: BringupEvidence) -> dspy.Prediction:
        self.log.reset()

        # (1) st-230, MECHANICAL. The PASS row is computed from the canary, never
        # asserted by a model. There is no signature here and there should not be one.
        if roster_pass(**evidence.criteria()):
            return dspy.Prediction(
                action="DISPATCH",
                recipe_name=evidence.recipe_name,
                timeout_s=timeout_for(evidence.benchmarked_p90_s),
                rationale="five PASS criteria met on a campaign target",
                logbook=list(self.log.queries),
            )

        # (2) st-216 / st-250. Genuine LM work: read the paper and the source, then say
        # what is wrong. The tools are the only route to a citable identifier.
        d = self.diagnose(
            recipe_name=evidence.recipe_name,
            pinned_source=evidence.pinned_source,
            invocation=evidence.invocation,
            failed_criteria=evidence.failed_criteria(),
            stderr_tail=evidence.stderr_tail,
            prior_attempts=evidence.prior_attempts,
        )

        # (3) The guard. st-250 is fail-closed: an UNAVAILABLE verdict reached without
        # all five indexes is not downgraded to something more convenient, it is
        # refused, and the campaign is told which lookups are outstanding.
        if d.cause == "UNAVAILABLE" and not self.log.satisfies_unavailability_rule():
            missing = sorted(set(REQUIRED_INDEXES) - self.log.indexes_queried())
            return dspy.Prediction(
                action="BLOCKED",
                recipe_name=evidence.recipe_name,
                cause=d.cause,
                finding=d.finding,
                evidence=list(getattr(d, "evidence", [])),
                rationale=f"st-250 unsatisfied; not yet queried: {', '.join(missing)}",
                logbook=list(self.log.queries),
            )

        # (4) More LM work: what should change next, named so it can be logged.
        p = self.propose(
            recipe_name=evidence.recipe_name,
            cause=d.cause,
            finding=d.finding,
            prior_attempts=evidence.prior_attempts,
        )

        # (5) st-260, MECHANICAL. A "difference" that restates a prior attempt is not
        # one. Rejecting it here routes to a drop, which is the behaviour st-260 asks
        # for -- killing a failing method quickly is correct.
        repeats = is_restatement(p.named_difference, evidence.prior_attempts)
        if p.worth_trying and not repeats:
            return dspy.Prediction(
                action="RETRY",
                recipe_name=evidence.recipe_name,
                cause=d.cause,
                finding=d.finding,
                evidence=list(getattr(d, "evidence", [])),
                named_difference=p.named_difference,
                concrete_change=p.concrete_change,
                logbook=list(self.log.queries),
            )

        # (6) The drop record. st-230 requires the consequence stated, so it is a
        # separate output field rather than something to hope for in free text.
        j = self.justify(
            recipe_name=evidence.recipe_name,
            cause=d.cause,
            finding=d.finding,
            roster_role=evidence.roster_role,
        )
        return dspy.Prediction(
            action="DROP",
            recipe_name=evidence.recipe_name,
            cause=d.cause,
            finding=d.finding,
            evidence=list(getattr(d, "evidence", [])),
            drop_reason=j.drop_reason,
            consequence=j.consequence,
            rationale="restated prior attempt" if repeats else "no attempt worth its compute",
            logbook=list(self.log.queries),
        )


class UnguardedTriage(dspy.Module):
    """The same slice with the obligations left in the prompt instead of in code.

    One ReAct over `TriageUnguarded`, whose docstring carries every rule the guarded
    version enforces as a predicate. No `roster_pass()` call, no logbook check, no
    restatement check -- the model is asked to honour st-230, st-216, st-250, st-260 and
    st-218 by reading them.

    Kept so the two can be scored by the same metric on the same evidence. The
    comparison is the experiment; this class is not advice.
    """

    def __init__(self, max_iters: int = 6):
        super().__init__()
        self.log = Logbook()
        self.triage = dspy.ReAct(TriageUnguarded, tools=make_tools(self.log),
                                 max_iters=max_iters)

    def forward(self, evidence: BringupEvidence) -> dspy.Prediction:
        self.log.reset()
        t = self.triage(
            recipe_name=evidence.recipe_name,
            pinned_source=evidence.pinned_source,
            invocation=evidence.invocation,
            failed_criteria=evidence.failed_criteria(),
            stderr_tail=evidence.stderr_tail,
            prior_attempts=evidence.prior_attempts,
        )
        return dspy.Prediction(
            action=t.action,
            recipe_name=evidence.recipe_name,
            cause=t.cause,
            finding=t.finding,
            evidence=list(t.evidence),
            named_difference=t.named_difference,
            rationale="unguarded: the model's own verdict, as given",
            logbook=list(self.log.queries),
        )
