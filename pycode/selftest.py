"""Exercises the pure logic in this package. Run by build.py; failing it fails the build.

The objective is ensuring that the arithmetic specified in the prompt (the 4:1
weighting, burn-rate adders, six sequential caps, rank key, and escalation ladder)
yields the exact figures stated in the prompt. A reconstruction that diverges from
its source would misrepresent the specifications.
"""

from __future__ import annotations

import math

from .campaign import BUDGET_USD, RANKING_ARMS, WALL_CLOCK_HOURS, DesignRow
from .deliverables import BROADCAST_ALLOWED, send
from .gates import NoveltyEvidence, monomer_foldability_gate, novelty_gate
from .governor import (
    Governor,
    burn_rate_usd_per_hour,
    derive_max_instances,
    next_ceiling,
    scale_up_triggered,
    submit_gate,
)
from .ledger import LedgerRow, campaign_totals, gen_backlog_ok, token_cost
from .orchestration import (
    WatchdogState,
    daemon_limit,
    lint_autonomy,
    lint_orchestrator_source,
    watchdog_action,
)
from .roster import may_reap, roster_pass, timeout_for
from .scoring import final_score, pose_dockq, pose_pass, rank_zscore
from .sheet import (
    SelectionCaps,
    enforce_selection_caps,
    levenshtein,
    rank_key,
    route_row,
)


def row(design_id: str, seq: str, **kw) -> DesignRow:
    base = dict(
        target="15-PGDH",
        designed_structure_path=f"/bundle/{design_id}.cif",
        root_backbone_id=kw.pop("root", design_id),
        structure_method=kw.pop("method", "rfdiffusion3"),
        seq_method=kw.pop("seq_method", "solublempnn"),
    )
    base.update(kw)
    return DesignRow(design_id=design_id, sequence=seq, **base)


def test_burn_rate_matches_the_prompts_worked_example() -> None:
    # "a typical 4-core/32-GiB H100 box is roughly $4.39/h all-in"
    rate = burn_rate_usd_per_hour("H100", cores=4, mem_gib=32)
    assert abs(rate - 4.39) < 0.005, rate
    # "$10,000 / 24 h = $417/h ... roughly 95 H100-equivalents with adders"
    assert abs(BUDGET_USD / WALL_CLOCK_HOURS - 416.67) < 0.01
    assert abs(BUDGET_USD / WALL_CLOCK_HOURS / rate - 94.83) < 0.01


def test_the_bootstrap_ratio_rounds_where_the_stated_formula_floors() -> None:
    """A small internal inconsistency the re-coding surfaces.

    The prompt says max_instances MUST be derived as floor(target_hourly_rate /
    weighted_per_sandbox_rate), which is floor(94.83) = 94. It then says the 150-instance
    bootstrap cap "runs about 1.58x even-pace": 1.58 corresponds to 150/95, the ratio
    against the *rounded* even-pace figure quoted in the prose. Against the floor its
    own rule specifies, the bootstrap cap runs 1.60x.

    Immaterial in dollars, but it is the kind of drift that only shows up when the prose
    is made to compute.
    """
    rate = burn_rate_usd_per_hour("H100", cores=4, mem_gib=32)
    assert derive_max_instances(rate) == 94
    assert abs(150 / 95 - 1.579) < 0.001              # the prompt's stated 1.58x
    assert abs(150 / derive_max_instances(rate) - 1.596) < 0.001   # its formula's answer


def test_governor_lowers_and_halts() -> None:
    gov = Governor(ceiling=150, set_at=0.0, basis="BUDGET", pct_elapsed=40.0,
                   calibrated=True, pct_spent_metered=56.0)
    assert next_ceiling(gov, live_gpu=10, over_ceiling_cycles=0, pace=56.0) == 0
    assert next_ceiling(gov, live_gpu=10, over_ceiling_cycles=2, pace=41.0) == 120
    boot = Governor(ceiling=100, set_at=0.0, basis="BOOTSTRAP", calibrated=False)
    assert next_ceiling(boot, live_gpu=0, over_ceiling_cycles=0, pace=1.0) == 125


def test_submit_gate_is_fail_closed() -> None:
    assert submit_gate("app", "tag", 60, read_file=None) is False          # raises -> False
    assert submit_gate("app", "tag", 60,
                       read_file=lambda _p: "not json") is False
    stale = '{"ceiling": 150, "set_at": 0.0, "basis": "BUDGET"}'
    assert submit_gate("app", "tag", 60, read_file=lambda _p: stale,
                       now=lambda: 10_000.0) is False


def test_scale_up_trigger_needs_three_cycles() -> None:
    under = [Governor(ceiling=150, set_at=0.0, basis="BUDGET",
                      pct_elapsed=50.0, pct_spent_metered=20.0) for _ in range(3)]
    assert scale_up_triggered(under)
    assert not scale_up_triggered(under[:2])


def test_token_cost_never_double_counts_cache_reads() -> None:
    # input_tokens already includes cache reads.
    cost = token_cost(input_tokens=1000, cache_read_tokens=800, output_tokens=100,
                      fresh_rate=3e-6, output_rate=15e-6, cache_read_rate=0.3e-6)
    assert abs(cost - (200 * 3e-6 + 100 * 15e-6 + 800 * 0.3e-6)) < 1e-12


def test_ledger_totals_exclude_the_intermediate_tier() -> None:
    rows = [
        LedgerRow(0, "j1", "t", "m", "gen_screen", 100, 0, 10.0, "f"),
        LedgerRow(0, "j2", "t", "m", "screen", 0, 100, 10.0, "f"),
        LedgerRow(0, "j3", "t", "m", "intermediate", 0, 40, 10.0, "f"),
        LedgerRow(0, "j4", "t", "m", "final", 0, 30, 10.0, "f"),
    ]
    assert campaign_totals(rows) == {
        "designs_generated": 100, "designs_screened": 100, "designs_ranked": 30}


def test_generation_cannot_outrun_scoring() -> None:
    def agg(_path: str) -> str:
        return '{"15-PGDH": {"gen": 5000, "scr": 100}}'
    assert gen_backlog_ok("15-PGDH", "gen_screen", agg) is False
    assert gen_backlog_ok("15-PGDH", "final", agg) is True        # not a generation stage

    def small(_path: str) -> str:
        return '{"15-PGDH": {"gen": 150, "scr": 0}}'
    assert gen_backlog_ok("15-PGDH", "generate", small) is True   # below the 200 floor


def test_novelty_thresholds() -> None:
    r = row("d1", "AAAA")
    assert novelty_gate(r, NoveltyEvidence(0.55, 0.9, 0.1, 10, 0.2))
    assert not novelty_gate(r, NoveltyEvidence(0.75, 0.9, 0.1, 10, 0.2))   # UniRef90
    assert not novelty_gate(r, NoveltyEvidence(0.1, 0.1, 0.35, 60, 0.2))   # local
    assert not novelty_gate(r, NoveltyEvidence(0.1, 0.1, 0.1, 10, 0.7))    # target mimic


def test_plddt_scale_is_normalised() -> None:
    r = row("d1", "AAAA")
    assert monomer_foldability_gate(r, mean_plddt=0.82)     # ESMFold2 emits 0-1
    assert monomer_foldability_gate(r, mean_plddt=82.0)
    assert not monomer_foldability_gate(r, mean_plddt=0.60)


def test_final_score_and_rank_zscore_weighting() -> None:
    r = row("d1", "AAAA")
    r.ipsae_min = {a: 0.8 for a in RANKING_ARMS}
    r.sc_dockq = {a: 0.4 for a in RANKING_ARMS}
    assert abs(final_score(r, RANKING_ARMS) - 0.6) < 1e-12
    stats = {f"ipsae_{a}": (0.6, 0.1) for a in RANKING_ARMS}
    stats.update({f"sc_dockq_{a}": (0.5, 0.1) for a in RANKING_ARMS})
    # ipSAE z = +2 weighted 4; DockQ z = -1 weighted 1 -> (3*4*2 + 3*1*-1) / 15
    assert abs(rank_zscore(r, RANKING_ARMS, stats) - (24 - 3) / 15) < 1e-12


def test_pose_is_the_weakest_arm() -> None:
    r = row("d1", "AAAA")
    r.sc_dockq = {"ef2full": 0.9, "ef2fast": 0.21, "ptxv2": 0.5}
    assert abs(pose_dockq(r) - 0.21) < 1e-12
    assert not pose_pass(r)                       # below the 0.23 default
    r.sc_dockq["ef2fast"] = 0.3
    assert pose_pass(r)


def test_reduced_mask_means_over_realized_terms_only() -> None:
    r = row("d1", "AAAA")
    r.ipsae_min = {"ef2full": 0.8, "ef2fast": math.nan, "ptxv2": 0.6}
    r.sc_dockq = {"ef2full": 0.4, "ef2fast": math.nan, "ptxv2": 0.4}
    assert abs(final_score(r, RANKING_ARMS) - 0.55) < 1e-12


def test_selection_caps_are_ceilings_on_the_selected_set() -> None:
    pool = []
    for i in range(40):
        pool.append(row(f"d{i}", "".join("ACDEFGHIKLMNPQRSTVWY"[(i + j) % 20]
                                         for j in range(30)),
                        root="root-A" if i < 20 else f"root-{i}",
                        method="rfdiffusion3" if i < 30 else "boltzgen"))
    for r in pool:
        r.tm90_cluster_id = f"c{hash(r.sequence) % 9}"
    selected = enforce_selection_caps(pool)
    counts = {}
    for r in selected:
        counts[r.root_backbone_id] = counts.get(r.root_backbone_id, 0) + 1
    assert max(counts.values()) <= math.ceil(0.05 * 30)
    methods = [r.structure_method for r in selected]
    assert max(methods.count(m) for m in set(methods)) <= 15


def test_levenshtein_cap_rejects_near_duplicates() -> None:
    a, b = "A" * 30, "A" * 28 + "CD"
    assert levenshtein(a, b) == 2
    caps = SelectionCaps()
    pool = [row("d1", a), row("d2", b)]
    for r in pool:
        r.tm90_cluster_id, r.root_backbone_id = "c1", r.design_id
    assert len(enforce_selection_caps(pool, caps=caps)) == 1


def test_rank_key_tiers_by_seed_count_then_pose() -> None:
    full = row("full", "A" * 30, n_seeds={a: 5 for a in RANKING_ARMS})
    full.pose_PASS, full.rank_zscore = False, 0.1
    short = row("short", "C" * 30, n_seeds={a: 3 for a in RANKING_ARMS})
    short.pose_PASS, short.rank_zscore = True, 9.9
    assert rank_key(full) > rank_key(short)       # tier beats a better score


def test_missing_gate_result_routes_to_unranked() -> None:
    r = row("d1", "A" * 30, n_seeds={a: 5 for a in RANKING_ARMS})
    r.tm90_cluster_id, r.fold_class = "c1", "all_alpha"
    r.final_score, r.pose_dockq = 0.6, 0.4
    r.gates = {"novelty": True}
    assert route_row(r, ("novelty", "liability"), True) == (
        "unranked", "missing gate result: liability")
    r.gates["liability"] = True
    assert route_row(r, ("novelty", "liability"), True) == ("ranked", None)


def test_reap_criterion_rejects_idle_heuristics() -> None:
    assert may_reap("success", 10, 100, True)
    assert may_reap("running", 250, 100, True)          # >2x benchmarked wall clock
    assert not may_reap("running", 150, 100, True)      # slow execution within allowable limits
    assert not may_reap("success", 10, 100, False)      # not in our job ledger
    assert timeout_for(2700) == 5400 and timeout_for(100) == 200


def test_roster_pass_needs_all_five() -> None:
    ok = dict(container_builds=True, weights_checksum_matches=True,
              end_to_end_exit_code=0, n_designs=3, parsed_structures=3,
              sequences_emitted=1)
    assert roster_pass(**ok)
    assert not roster_pass(**{**ok, "n_designs": 1})            # not in [2,4]
    assert not roster_pass(**{**ok, "parsed_structures": 2})    # fewer than n_designs
    assert not roster_pass(**{**ok, "sequences_emitted": 0})    # adapter did not consume


def test_watchdog_ladder_and_independent_runaway_brake() -> None:
    fresh = WatchdogState(1.0, 1.0, live_gpu=10, ceiling=150, runaway_cycles=0)
    assert watchdog_action(fresh) == []
    stale = WatchdogState(20.0, 1.0, live_gpu=10, ceiling=150, runaway_cycles=0)
    assert "post stall notice" in watchdog_action(stale)
    assert not any("ceiling=0" in a for a in watchdog_action(stale))
    dead = WatchdogState(40.0, 25.0, live_gpu=10, ceiling=150, runaway_cycles=0)
    actions = watchdog_action(dead)
    assert 'write ceiling=0 basis="DEAD_ORCHESTRATOR"' in actions
    assert "re-dispatch BUDGET" in actions
    # Fires with a perfectly fresh heartbeat: the two detectors are independent.
    runaway = WatchdogState(1.0, 1.0, live_gpu=400, ceiling=150, runaway_cycles=2)
    assert 'write ceiling=0 basis="WATCHDOG_RUNAWAY"' in watchdog_action(runaway)


def test_daemon_limit_is_bounded() -> None:
    assert daemon_limit(150, 10) == 160
    assert daemon_limit(150, 500) == 200        # N capped at 50, then the hard 200
    assert daemon_limit(0, 0) == 1


def test_orchestrator_lint_catches_the_named_calls() -> None:
    bad = "import modal\nimport time\nwhile True:\n    time.sleep(5)\n"
    found = lint_orchestrator_source(bad)
    assert any("imports modal" in v for v in found)
    assert any("calls time.sleep" in v for v in found)
    assert "foreground while-True loop" in found
    good = "from external import host\nhost.wait_for_notification(timeout=300)\n"
    assert lint_orchestrator_source(good) == []


def test_autonomy_lint() -> None:
    assert lint_autonomy("ask_user('is this ok?')") == ["calls ask_user"]
    assert lint_autonomy("host.send_message(kind='question')") == []


def test_broadcast_is_restricted_to_three_messages() -> None:
    send("in thread", "1.0")
    send("morning", "1.0", reply_broadcast=True, kind="daily morning update")
    try:
        send("look at this", "1.0", reply_broadcast=True, kind="progress")
    except ValueError:
        pass
    else:                                        # pragma: no cover
        raise AssertionError("broadcast should have been refused")
    assert len(BROADCAST_ALLOWED) == 3


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
    print(f"pycode selftest: {len(tests)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
