"""The ledgers, and the rule that every reported number is a fresh aggregate over one.

The recurring shape here is: one writer per file, totals defined once as a sum over the
tree, and no number ever reaching a report except through a single saved function that
recomputes it at post time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from .campaign import LEDGER, STATE

# ── the design-count ledger ───────────────────────────────────────────────────────────

# @block st-145 kind=schema
@dataclass
class LedgerRow:
    """One row per job completion. The whole schema, deliberately minimal."""

    ts_utc: float
    job_id: str
    target: str
    structure_method: str
    stage: str                  # generate | gen_screen | screen | intermediate | final
    n_generated: int
    n_scored: int
    gpu_seconds: float
    writer_frame_id: str


def ledger_path(writer_frame_id: str) -> str:
    """One file per writing frame -- never a single shared file.

    Volume appends across concurrent sandboxes are not atomic and silently clobber, so
    a single shared ledger loses rows without erroring. A per-writer subfile tree makes
    concurrent appends structurally safe and the total a sum over the tree.
    """
    return f"{LEDGER}/{writer_frame_id}.jsonl"


GEN_SCREEN_INSTRUMENTS = ("ESMFold2-Full", "ESMFold2-Fast", "Protenix v2")


def gen_screen_job(target: str, n_backbones: int, write_row) -> None:
    """The unit of generation work: generate, filter in-job, then 1-seed screen.

    The n_generated row is written before the screen so the method-floor matrix sees the
    survivors immediately. Where the structure tool's image cannot carry the screening
    stacks, the screen is chained as an immediately-dispatched job on the same
    survivors -- a queued-but-undrained arm is a logged deviation.
    """
    survivors = generate_and_filter(target, n_backbones)
    write_row(stage="gen_screen", n_generated=len(survivors), n_scored=0)
    scored = screen_one_seed(survivors, GEN_SCREEN_INSTRUMENTS)
    write_row(stage="gen_screen", n_generated=0, n_scored=scored)


def generate_and_filter(target: str, n_backbones: int) -> list:
    """Novelty, liability, monomer-foldability and structural-plausibility, in-job."""
    return []


def screen_one_seed(survivors: list, instruments) -> int:
    return 0


# ── what the totals mean ──────────────────────────────────────────────────────────────

# @block st-147 kind=logic
GEN_BACKLOG_FLOOR = 200
GEN_BACKLOG_MULTIPLE = 2
GEN_BACKLOG_SCORED_FLOOR = 50


def campaign_totals(rows: list[LedgerRow]) -> dict[str, int]:
    """Fixed at kickoff, and the only definition used anywhere.

    Note that the intermediate tier counts toward neither total: it is recorded under
    its own stage so that 'screened' and 'ranked' keep meaning the same thing all the
    way through the campaign. Any redefinition mid-campaign is a logged deviation with a
    one-time reconciliation row.
    """
    return {
        "designs_generated": sum(r.n_generated for r in rows),
        "designs_screened": sum(r.n_scored for r in rows if r.stage == "screen"),
        "designs_ranked": sum(r.n_scored for r in rows if r.stage == "final"),
    }


def assert_not_silently_empty(rows: list[LedgerRow], first_wave_complete: bool) -> None:
    """An empty ledger after the first scoring wave is fail-loud, not a zero to report.

    Reporting zero here is the failure mode that looks like a working campaign.
    """
    assert rows or not first_wave_complete, "ledger empty after first scoring wave"


def gen_backlog_ok(target: Optional[str], stage: Optional[str], read_file) -> bool:
    """`submit_gate` step (d2): generation cannot outrun scoring.

    A backstop independent of the in-job coupling, because the coupling can be broken by
    a chained screen that never drains. BUDGET publishes the aggregate; the gate reads it
    fresh on every generation dispatch.
    """
    if stage not in ("generate", "gen_screen") or target is None:
        return True
    try:
        agg = json.loads(read_file(f"{STATE}/ledger_agg.json"))
    except (OSError, ValueError, TypeError):
        return True
    counts = agg.get(target, {})
    gen, scr = counts.get("gen", 0), counts.get("scr", 0)
    if gen < GEN_BACKLOG_FLOOR:
        return True
    return gen <= GEN_BACKLOG_MULTIPLE * max(scr, GEN_BACKLOG_SCORED_FLOOR)


IDEMPOTENCY_KEY = ("job_id", "stage")


def never_move_in_flight(path: str, jobs_writing_into: int) -> None:
    """Never mv or rewrite a shared directory while jobs that write into it are live,
    and route every shared append through its owning singleton after a fresh re-mount --
    an append against a stale FUSE snapshot clobbers the file."""
    assert jobs_writing_into == 0, f"{path} has {jobs_writing_into} writers in flight"


# ── token accounting ──────────────────────────────────────────────────────────────────

# @block st-141 kind=logic
def token_cost(input_tokens: int, cache_read_tokens: int, output_tokens: int,
               fresh_rate: float, output_rate: float, cache_read_rate: float) -> float:
    """Exactly this formula, because input_tokens already includes cache reads.

    Billing cache reads at the fresh rate, or adding them twice, are the two ways to get
    this wrong, and both inflate the reported figure rather than deflating it -- which
    means the error would never show up as a budget overrun.
    """
    fresh_input = input_tokens - cache_read_tokens
    return (fresh_input * fresh_rate
            + output_tokens * output_rate
            + cache_read_tokens * cache_read_rate)


def spend_number_for_slack(sql: str, execute) -> float:
    """Every ledger or spend number posted must come from a server-side SUM executed in
    the same cell that composes the post. Hand-built rate arithmetic and client-side row
    summing are forbidden."""
    assert sql.strip().upper().startswith("SELECT SUM"), "aggregate server-side"
    return execute(sql)


# ── reporting ─────────────────────────────────────────────────────────────────────────

# @block st-172 kind=protocol
def scribe_figures(query, ledger: str) -> dict:
    """ONE saved SCRIBE function is the sole source of every number in every report.

    It runs a fresh server-side aggregate at post time and asserts the truncation flag is
    false. No number is filled from memory, from a cached snapshot, from client-side
    summation over returned rows, or from output-file counts. A fabricated or stale
    figure is a worse failure than a missing one.
    """
    result = query(f"SELECT SUM(n_generated), SUM(n_scored) FROM {ledger}")
    assert not result.truncated, "aggregate truncated; the figure would be wrong"
    return {"n_generated": result[0], "n_scored": result[1]}


# @block st-171 kind=schema
PACE_MARKS = ("AHEAD", "ON-PACE", "BEHIND", "OVER")
BASIS_TAGS = ("METERED", "ESTIMATE")


def status_block(figures: dict, gov, deviations_count: int) -> dict:
    """The fixed-format block that ends every hourly update, fields (a) through (f).

    The uncalibrated rule is the sharp edge: an ESTIMATE-based mark reads UNCALIBRATED
    as its ENTIRE pace field. No pace adjective may accompany it, because "ON-PACE
    (estimate)" reads as reassurance and the estimate is exactly what is in doubt.
    """
    calibrated = gov.calibrated
    pace_field = pace_mark(gov) if calibrated else "UNCALIBRATED"
    return {
        "a_active": {"gpu_jobs": gov.live_sb, "sub_agents": figures.get("agents_live", 0)},
        "b_designs": {"generated": figures["n_generated"], "scored": figures["n_scored"]},
        "c_spend": {"usd": gov.metered_usd, "pace": pace_field,
                    "basis": "METERED" if calibrated else "ESTIMATE"},
        "d_tokens": figures.get("tokens", {}),
        "e_projected_completion": figures.get("eta"),
        "f_deviations": deviations_count or "none",
    }


def pace_mark(gov) -> str:
    delta = gov.pct_spent_metered - gov.pct_elapsed
    if delta >= 15:
        return "OVER"
    if delta > 5:
        return "AHEAD"
    return "BEHIND" if delta < -20 else "ON-PACE"


def deviation_row(at_utc: str, kind: str, target: str, what: str, action: str) -> str:
    """One JSONL row per deviation, in an append-only file never overwritten in place."""
    return json.dumps({"at_utc": at_utc, "kind": kind, "target": target,
                       "what": what, "action": action})


DEVIATIONS_PATH = f"{LEDGER}/deviations.jsonl"
