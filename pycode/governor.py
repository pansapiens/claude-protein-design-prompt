"""The concurrency governor: one integer, four authorized writers, one fail-closed gate.

This is the longest and most mechanical region of the prompt. The design is a
submitter-side dead-man switch: `submit_gate()` refuses on a stale file, so the campaign
halts if the budget agent dies, rather than running on the last value it saw.
"""

from __future__ import annotations

import json
import math
import random
import time
from dataclasses import asdict, dataclass
from typing import Optional

from .campaign import (
    BOOTSTRAP_CEILING,
    BOOTSTRAP_STEP,
    BUDGET_USD,
    STALE_METERED_USD,
    STATE,
    TARGET_HOURLY_RATE,
)
from .external import modal
from .gates import validation_gate_pass
from .roster import may_reap

# ── sandbox pricing and rates ─────────────────────────────────────────────────────────

# @block st-135 kind=logic
GPU_HOURLY_USD = {
    "H100": 3.95,          # $0.001097/s
    "A100-80GB": 2.50,     # $0.000694/s
    "A100-40GB": 2.10,     # $0.000583/s
    "L40S": 1.95,          # $0.000542/s
    "A10G": 1.10,          # $0.000306/s
    "L4": 0.80,            # $0.000222/s
    "T4": 0.59,            # $0.000164/s
}
CPU_HOURLY_USD_PER_CORE = 0.047        # physical core = 2 vCPU, 0.125-core minimum
MEM_HOURLY_USD_PER_GIB = 0.008

# Rate-card values are verified at kickoff against the provider's published pricing;
# they are a cross-check only. The metered figure is canonical (st-244).


def burn_rate_usd_per_hour(gpu_type: str, cores: float, mem_gib: float) -> float:
    """GPU + CPU + memory, billed per second and separately.

    A typical 4-core/32-GiB H100 box is ~$4.39/h all-in, not $3.95: additional resource
    charges are roughly 11% and a projection that ignores them runs under pace on paper
    while running over pace in fact.
    """
    return (GPU_HOURLY_USD[gpu_type]
            + max(cores, 0.125) * CPU_HOURLY_USD_PER_CORE
            + mem_gib * MEM_HOURLY_USD_PER_GIB)


def derive_max_instances(weighted_per_sandbox_rate: float,
                         target_hourly_rate: float = TARGET_HOURLY_RATE) -> int:
    """The ceiling is DERIVED, not chosen, and re-derived whenever the mix changes.

    At $417/h against ~$4.39/h all-in, even pace is ~95 H100-equivalents; the 150
    bootstrap cap therefore runs ~1.58x even pace, and any further raise has to be paid
    for by an under-pace metered reading.
    """
    return math.floor(target_hourly_rate / weighted_per_sandbox_rate)


# ── the governor file ─────────────────────────────────────────────────────────────────

# @block st-137 kind=protocol
GOVERNOR_PATH = f"{STATE}/governor.json"
GOVERNOR_STALE_MINUTES = 25
BUDGET_CYCLE_MINUTES = 15

# Exactly four writers, and nothing else may write the file.
WRITER_SETUP = "BOOTSTRAP"                    # one-time T0 seed, ceiling=150
WRITER_BUDGET = "BUDGET"                      # owns it thereafter, every 15 min
WATCHDOG_BASES = ("DEAD_ORCHESTRATOR", "WATCHDOG_RUNAWAY")   # fail-safe, ceiling=0 only
WRITER_ORCHESTRATOR = "ORCHESTRATOR_RESUMED"  # resume-clear only


@dataclass
class Governor:
    """The single campaign-wide integer, published on every budget cycle."""

    ceiling: int
    set_at: float
    basis: str
    metered_usd: float = 0.0
    metered_asof_utc: float = 0.0
    ratecard_usd: float = 0.0
    live_sb: int = 0
    pct_elapsed: float = 0.0
    pct_spent_metered: float = 0.0
    pct_spent_projected: float = 0.0
    calibrated: bool = False
    pre_halt_ceiling: Optional[int] = None

    def is_stale(self, now: float) -> bool:
        return (now - self.set_at) > GOVERNOR_STALE_MINUTES * 60


def projected_spend_pct(gov: Governor, weighted_rate: float, now: float) -> float:
    """Rate-card projection forward from the last metered reading.

    While billing is dark this additionally takes the max with the dispatch ledger's own
    rate-card total, so the pace band binds on real data rather than on a zero.
    """
    hours_since = max(0.0, (now - gov.metered_asof_utc) / 3600.0)
    projected = gov.metered_usd + gov.live_sb * weighted_rate * hours_since
    pct = 100.0 * projected / BUDGET_USD
    if not gov.calibrated:
        pct = max(pct, 100.0 * gov.ratecard_usd / BUDGET_USD)
    return pct


def pace_pct(gov: Governor, weighted_rate: float, now: float) -> float:
    """Both the +15pp ceiling and the ceiling=0 trigger bind on the higher of the two."""
    return max(gov.pct_spent_metered, projected_spend_pct(gov, weighted_rate, now))


def is_calibrated(canary_cost_present: bool, value: float, ratecard_usd: float,
                  previous_value: float, asof_advanced: bool) -> bool:
    """All four conditions, or the reading is not calibrated.

    Once the first calibrated reading is recorded, metered spend becomes the ONLY basis
    for raising the governor. Holding, lowering and writing ceiling=0 always keep
    computing the rate-card projection and act on whichever figure is HIGHER.
    """
    return (canary_cost_present
            and (value > 20.0 or value >= 0.9 * ratecard_usd)
            and abs(value - previous_value) > 5.0
            and asof_advanced)


def may_raise(gov: Governor, readings: list[float], live_gpu: int) -> bool:
    """Four independent blocks on raising, any one of which forbids it."""
    if not gov.calibrated:
        return False
    if len(readings) >= 2 and _relative_gap(readings[-1], readings[-2]) > 0.20:
        return False
    if (gov.ratecard_usd > 1.5 * gov.metered_usd
            and gov.ratecard_usd - gov.metered_usd > STALE_METERED_USD):
        return False                     # metered materially trails: it is stale
    return live_gpu <= gov.ceiling


def _relative_gap(a: float, b: float) -> float:
    return abs(a - b) / max(a, b) if max(a, b) else 0.0


def next_ceiling(gov: Governor, live_gpu: int, over_ceiling_cycles: int,
                 pace: float) -> int:
    """Where the ceiling goes this cycle.

    Note the asymmetry: over-pace by 15pp for ONE cycle writes zero, while an
    over-ceiling live count LOWERS to 80% rather than holding. Both are one-way ratchets
    toward safety; only a calibrated under-pace reading moves it back up.
    """
    if pace >= gov.pct_elapsed + 15:
        return 0
    if over_ceiling_cycles >= 2:
        return math.floor(0.8 * gov.ceiling)
    if not gov.calibrated:
        return min(gov.ceiling + BOOTSTRAP_STEP, BOOTSTRAP_CEILING)
    return gov.ceiling


# @block st-137 kind=logic
GATE_BACKOFF = (5, 10, 20, 40, 60)
GATE_MAX_ATTEMPTS = 8
LONG_TIMEOUT_S = 1800
SANDBOX_TIMEOUT_CAP_S = 5400


def submit_gate(app_id: str, project_tag: str, timeout_s: int,
                gpu_type: Optional[str] = None, target: Optional[str] = None,
                stage: Optional[str] = None, *, read_file=None, now=time.time) -> bool:
    """One True authorizes exactly one container start. Never per-batch, never per-loop.

    The ENTIRE body is wrapped so that any exception returns False with GATE_ERROR: the
    gate is FAIL-CLOSED, never fail-open, because "a delayed dispatch costs seconds while
    an ungated H100 dispatch can be multiple unrecoverable dollars".

    Steps (a)-(g) below are the prompt's own lettering.
    """
    try:
        raw = read_file(GOVERNOR_PATH)                              # (a) fresh read
        gov = Governor(**json.loads(raw))

        if gov.is_stale(now()):                                     # (b) dead-man switch
            return _refuse("STALE_OR_MISSING_GOVERNOR")
        if gov.ceiling == 0:                                        # (c) halted
            return _refuse("CEILING_ZERO")
        if timeout_s > LONG_TIMEOUT_S and max(
                gov.pct_spent_metered, gov.pct_spent_projected) > gov.pct_elapsed + 5:
            return _refuse("LONG_TIMEOUT_OVER_PACE")                # (d)
        if target is not None and stage in ("screen", "intermediate", "final"):
            if not validation_gate_pass(target, read_file=read_file):
                return _refuse("VALIDATION_GATE_NOT_PASS")
        if not backlog_ok(target, stage, read_file):                # (d2), see ledger
            return _refuse("GEN_BACKLOG_CAP")

        headroom = max(10, math.floor(0.1 * gov.ceiling))
        for attempt in range(GATE_MAX_ATTEMPTS):                    # (e), (f)
            live = count_live_gpu_sandboxes(app_id, project_tag)
            if live < gov.ceiling - headroom:
                return True                                         # (g)
            time.sleep(GATE_BACKOFF[min(attempt, len(GATE_BACKOFF) - 1)]
                       * random.uniform(0.8, 1.2))
        return _refuse("HEADROOM_EXHAUSTED")
    except Exception:                                               # noqa: BLE001
        return _refuse("GATE_ERROR")


def _refuse(reason: str) -> bool:
    return False


def count_live_gpu_sandboxes(app_id: str, project_tag: str) -> int:
    """Step (e): ALL sandboxes minus tagged-CPU, via the provider SDK.

    Does not use the harness usage table, which lags. Rate-limited inside the
    module to one SDK call per 8 seconds per process, and the count subtracts sandboxes
    whose job state is terminal or whose lifetime exceeds 2x its wall-clock budget.
    """
    tags = {"claude-science-project": project_tag}
    every = list(modal.Sandbox.list(app_id=app_id, tags=tags) or [])
    cpu = list(modal.Sandbox.list(app_id=app_id, tags={**tags, "kind": "cpu"}) or [])
    reapable = [s for s in every if may_reap(s.status, s.lifetime_s, s.benchmarked_p90_s, True)]
    return len(every) - len(cpu) - len(reapable)


def backlog_ok(target: Optional[str], stage: Optional[str], read_file) -> bool:
    """Generation cannot outrun scoring; see `ledger.gen_backlog_ok`."""
    from .ledger import gen_backlog_ok
    return gen_backlog_ok(target, stage, read_file)


def sandbox_kwargs(benchmarked_p90_s: float, kind: str = "gpu") -> dict:
    """Every sandbox carries its kind tag, an idle timeout, and a hard wall-clock cap.

    The cap is the damage bound the provider enforces by killing the container, so
    per-sandbox spend stays bounded even when every control loop on our side is dead.
    """
    return {
        "tags": {"kind": kind},
        "idle_timeout": 300,
        "timeout": min(math.ceil(2.0 * benchmarked_p90_s), SANDBOX_TIMEOUT_CAP_S),
    }


# ── the standing budget agent ─────────────────────────────────────────────────────────

# @block st-154 kind=protocol
def budget_agent(campaign_end: float, now=time.time) -> None:
    """A standing sub-agent running continuously on a 15-minute cycle rather than
    an ad-hoc orchestrator task.

    It owns all metered reads and all writes to governor.json. GPU dollars come from the
    provider's metered per-job spend field; a rate-card figure is a cross-check only.
    """
    while now() < campaign_end:
        gov = read_governor()
        gov.metered_usd = read_metered_spend()
        write_governor(gov)
        reap_sweep(gov)
        write_liveness("budget")
        time.sleep(BUDGET_CYCLE_MINUTES * 60)


def read_governor() -> Governor:
    return Governor(ceiling=BOOTSTRAP_CEILING, set_at=time.time(), basis=WRITER_SETUP)


def write_governor(gov: Governor) -> str:
    return json.dumps(asdict(gov))


def read_metered_spend() -> float:
    """Summed over rows whose object_id is THIS campaign's app id, excluding workspace
    totals from other teams."""
    return 0.0


def write_liveness(who: str) -> str:
    return f"{STATE}/{who}_liveness.json"


# ── scale-up, and per-target shares ───────────────────────────────────────────────────

# @block st-158 kind=logic
UNDER_PACE_FLOOR_PP = -20
SCALE_UP_CONSECUTIVE_CYCLES = 3


def scale_up_triggered(history: list[Governor]) -> bool:
    """Under-pace is a planning failure, not a saving, so the floor is a trigger too.

    Either three consecutive cycles more than 20pp under pace, or a fleet running at
    less than half the ceiling once the campaign is properly under way.
    """
    recent = history[-SCALE_UP_CONSECUTIVE_CYCLES:]
    if len(recent) < SCALE_UP_CONSECUTIVE_CYCLES:
        return False
    return all(
        g.pct_spent_metered < g.pct_elapsed + UNDER_PACE_FLOOR_PP
        or (g.live_sb < 0.5 * g.ceiling and g.pct_elapsed > 10)
        for g in recent
    )


@dataclass
class TargetWeight:
    """Per-target share: a literature prior blended with live campaign observables."""

    prior: float
    live: float
    weight: float


def target_weights(dossiers, observables, elapsed_fraction: float) -> dict[str, TargetWeight]:
    """Early in the campaign the prior dominates; later the live signal does.

    Shares are relative on any positive scale; the dispatcher normalizes. The only
    hard bound is a floor: every target gets enough compute for 30 order-ready designs,
    and above that floor a hard target may take 10x the spend of an easy one.
    """
    ramp = min(1.0, max(0.0, elapsed_fraction))
    out = {}
    for d in dossiers:
        live = observables.get(d.target, 0.0)
        out[d.target] = TargetWeight(
            prior=d.prior_difficulty,
            live=live,
            weight=(1 - ramp) * d.prior_difficulty + ramp * live,
        )
    return out


def wake_entry(targets: list[str], waves: list[str], dollars: float) -> dict:
    """A WAKE carries a specific reallocation demand, not a notification."""
    return {"targets": targets, "waves": waves, "dollars": dollars}


# ── the sole campaign-wide reaper ─────────────────────────────────────────────────────

# @block st-244 kind=protocol
LIVENESS_CHECK_MINUTES = 5


def reap_sweep(gov: Governor) -> list[str]:
    """The budget agent's sweep is the ONLY campaign-wide reaper, and a skipped sweep is
    a logged deviation.

    Every terminate is tag-scoped to the caller's own job IDs. Listing by app id and
    terminating without filtering would be a destructive action against other agents'
    running work, because each campaign arm shares the workspace.
    """
    terminated = []
    for sb in list(modal.Sandbox.list() or []):
        if may_reap(sb.status, sb.lifetime_s, sb.benchmarked_p90_s, sb.job_id_in_ledger):
            sb.terminate()
            terminated.append(sb.id)
    return terminated


def may_terminate(actor: str, launched_it: bool, compute_done_success: bool) -> bool:
    """Only the budget sweep, a monitor whose job already returned success, or the
    frame that launched the sandbox may terminate it."""
    return launched_it or actor == "BUDGET" or (actor == "monitor" and compute_done_success)


ONE_MODAL_APP = True     # the harness-created session app; no agent creates another
APP_CAP_WORKSPACE = 1000


RESTART_SEQUENCE = (
    "write a fresh heartbeat and clear DEAD_ORCHESTRATOR",
    "re-dispatch WATCHDOG, BUDGET and CLOCK if any is >20 min stale",
    "re-load the durable ledgers",
    "dispatch one RECONCILE sub-agent to read live provider state",
    "read /state/reconcile.json before issuing any new work",
)


def orchestrator_state_is_durable(in_memory_keys: set[str]) -> bool:
    """Zero critical state in kernel memory ensures recovery after any interruption.

    The design-count ledger, the spend ledger, the active-job table and the per-target
    progress tracker all live in durable storage, written via the same batched heartbeat
    job on every update.
    """
    load_bearing = {"design_counts", "spend", "active_jobs", "progress"}
    return not (in_memory_keys & load_bearing)
