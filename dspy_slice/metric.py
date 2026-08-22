"""The campaign's own rules, as a DSPy metric.

This is the load-bearing claim of the experiment. DSPy asks for a metric: a function of
(example, prediction) returning a score, used by `Evaluate` to measure and by the
optimizers to search. The campaign prompt is largely a list of obligations that a
correct output must satisfy. Those are the same object.

So the 81 MUST blocks do not become prose in a signature's docstring hoping to be
remembered. They become checks here, where they are executed on every output. Five of
them are encoded below; each names its block.

Note what the metric can and cannot see. `st_218_evidence_is_fetched` works only because
`Logbook` recorded what this session retrieved -- provenance has to be built into the
program before it can be scored. A metric cannot recover a citation's origin after the
fact, which is the practical reason st-218 is written as a rule about writing rather
than a rule about checking.
"""

from __future__ import annotations

from dataclasses import dataclass

from pycode.roster import roster_pass

from .lookups import REQUIRED_INDEXES
from .program import is_restatement


@dataclass
class Check:
    block: str
    name: str
    passed: bool
    detail: str = ""


def st_230_pass_row_is_computed(example, pred) -> Check:
    """A method dispatches if and only if the five criteria hold on the canary."""
    should_dispatch = roster_pass(**example.evidence.criteria())
    did_dispatch = pred.action == "DISPATCH"
    return Check(
        "st-230", "dispatch iff PASS row", should_dispatch == did_dispatch,
        f"criteria={'PASS' if should_dispatch else 'FAIL'} action={pred.action}",
    )


def st_250_unavailable_needs_five_lookups(example, pred) -> Check:
    """UNAVAILABLE is only reachable after every named index has been queried."""
    queried = {index for index, _ in getattr(pred, "logbook", [])}
    claimed = getattr(pred, "cause", "") == "UNAVAILABLE" and pred.action != "BLOCKED"
    ok = (not claimed) or set(REQUIRED_INDEXES) <= queried
    return Check("st-250", "unavailability needs all five indexes", ok,
                 f"queried={sorted(queried)}")


def st_216_read_paper_before_blaming_tool(example, pred) -> Check:
    """A method is not declared broken before its own paper has been re-read."""
    queried = {index for index, _ in getattr(pred, "logbook", [])}
    blames_tool = getattr(pred, "cause", "") in ("UPSTREAM_BROKEN", "KNOWN_LIMITATION")
    ok = (not blames_tool) or ("corpus" in queried and "github" in queried)
    return Check("st-216", "paper and source read before blaming the method", ok,
                 f"cause={getattr(pred, 'cause', '-')}")


def st_260_retry_names_a_difference(example, pred) -> Check:
    """Every retry differs from the prior attempt in a way that can be named."""
    if pred.action != "RETRY":
        return Check("st-260", "retry names a real difference", True, "not a retry")
    diff = getattr(pred, "named_difference", "")
    ok = bool(diff.strip()) and not is_restatement(diff, example.evidence.prior_attempts)
    return Check("st-260", "retry names a real difference", ok, f"named={diff!r}")


def st_218_evidence_is_fetched(example, pred) -> Check:
    """Every identifier cited is the literal output of a lookup run in this session."""
    fetched = {index for index, _ in getattr(pred, "logbook", [])}
    cited = [e for e in getattr(pred, "evidence", []) if e.strip()]
    unsourced = [e for e in cited if e.split(":", 1)[0].strip().lower() not in fetched]
    return Check("st-218", "citations trace to an executed lookup", not unsourced,
                 f"unsourced={unsourced}" if unsourced else f"{len(cited)} cited")


CHECKS = (
    st_230_pass_row_is_computed,
    st_250_unavailable_needs_five_lookups,
    st_216_read_paper_before_blaming_tool,
    st_260_retry_names_a_difference,
    st_218_evidence_is_fetched,
)


def report(example, pred) -> list[Check]:
    return [check(example, pred) for check in CHECKS]


def campaign_metric(example, pred, trace=None) -> float:
    """The DSPy metric: fraction of the encoded obligations the output satisfies.

    `trace` is not None when an optimizer is bootstrapping demonstrations, and DSPy
    expects a bool there. A demonstration that violates a campaign rule must never be
    promoted into a prompt, so bootstrapping demands all of them.
    """
    checks = report(example, pred)
    if trace is not None:
        return all(c.passed for c in checks)
    return sum(c.passed for c in checks) / len(checks)
