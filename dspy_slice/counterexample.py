"""The negative control: st-137's submit_gate written as a DSPy signature.

Included because "can this be decomposed into signatures?" is only answerable if the
failure case is also on the table. This one is written out, runs, and is wrong.

`submit_gate()` authorizes exactly one container start. Its body is seven lettered
steps, each a comparison between numbers read from `/state/governor.json` and the live
sandbox count, wrapped so that ANY exception returns False. The prompt's own words for
the property that matters: the gate is fail-closed, "because a delayed dispatch costs
seconds while an ungated H100 dispatch costs unrecoverable dollars".

A signature cannot have that property. The failure mode of a predicate is an exception,
which `except: return False` converts into a refusal. The failure mode of a language
model is a confident, well-formatted answer, and there is no `except` clause for it.
Wrapping the call does not help: the wrapper catches transport errors, not wrong ones.

Run `python -m dspy_slice.demo` to see the numbers this module computes.
"""

from __future__ import annotations

from typing import Literal

import dspy


class GateDecision(dspy.Signature):
    """Decide whether one GPU container may start, per the campaign governor.

    Refuse if the governor file is stale, if the ceiling is zero, if a long-timeout job
    is requested while spend leads elapsed by more than 5 points, if the target's
    validation gate is not PASS, if generation is running more than the permitted
    multiple ahead of scoring, or if live sandboxes are within the headroom band of the
    ceiling. Otherwise allow.
    """

    governor_json: str = dspy.InputField()
    live_gpu_sandboxes: int = dspy.InputField()
    timeout_s: int = dspy.InputField()
    stage: str = dspy.InputField()
    validation_gate_status: str = dspy.InputField()

    decision: Literal["ALLOW", "REFUSE"] = dspy.OutputField()
    reason: str = dspy.OutputField()


# ── what this costs, in the campaign's own units ──────────────────────────────────────
#
# All five figures below are the prompt's, from st-135 and st-137: a $10,000 / 24 h
# budget, a governor ceiling of 150, an H100 sandbox at roughly $4.39/h all-in, and a
# per-job timeout of min(2 x p90, 5400 s). The job duration is the free parameter, so
# the estimate is reported as a band.

CEILING = 150
CAMPAIGN_HOURS = 24
BUDGET_USD = 10_000
SANDBOX_USD_PER_HOUR = 4.39


def dispatches(job_minutes: float) -> int:
    """One submit_gate() call per container start, at a full ceiling."""
    return int(CEILING * CAMPAIGN_HOURS * (60.0 / job_minutes))


def gate_as_llm_cost(job_minutes: float, usd_per_call: float = 0.004) -> dict[str, float]:
    """The gate is on the dispatch path, so an LM there is billed per dispatch.

    The dollars are the small half of the objection. The other two columns are the
    real ones: added latency on a path that already backs off 5-60 s under contention,
    and wrong decisions, which at any plausible error rate are not rare events.
    """
    n = dispatches(job_minutes)
    return {
        "job_minutes": job_minutes,
        "dispatches": n,
        "usd_of_gate_calls": n * usd_per_call,
        "wrong_at_0.1pct": n * 0.001,
        "wrong_at_1pct": n * 0.01,
        "ungated_h100_hours_per_wrong_allow": 1.5,
        "usd_per_wrong_allow": 1.5 * SANDBOX_USD_PER_HOUR,
    }


def summary_rows() -> list[dict[str, float]]:
    return [gate_as_llm_cost(m) for m in (5.0, 15.0, 45.0)]
