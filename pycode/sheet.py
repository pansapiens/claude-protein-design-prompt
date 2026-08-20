"""The sheet writer: provenance, selection caps, schema, ranking, and the companions.

This module is where most of the campaign's MECHANICAL clauses land, because the sheet
writer is the component the prompt trusts least to be remembered and most to be enforced:
it recomputes every gate from raw inputs before admitting a row, and it enforces the
diversity caps by selection-order algorithm rather than by a per-row flag.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .campaign import (
    AGREEMENT_TOL,
    MIN_DISTINCT_STRUCTURE_METHODS,
    RANKING_ARMS,
    SEEDS_FINAL,
    SHEET_ROWS_PER_TARGET,
    STATE,
    DesignRow,
)
from .gates import (
    liability_gate,
    monomer_foldability_gate,
    novelty_gate,
    structural_plausibility_gate,
)
from .scoring import final_score, pose_dockq, pose_pass, rank_zscore, scores_agree

# ── provenance ────────────────────────────────────────────────────────────────────────

# @block st-90 kind=protocol
METHOD_VOCAB_PATH = f"{STATE}/method_vocab.json"


@dataclass(frozen=True)
class MethodVocab:
    """Written once by the orchestrator at roster validation, then frozen.

    structure_method and seq_method are NOT free text. One token per tool, with
    rfdiffusion and rfdiffusion3 distinct -- collapsing two model generations into one
    token would silently corrupt every per-method count and cap downstream.
    """

    structure_methods: frozenset[str]
    seq_methods: frozenset[str]
    family_of: dict[str, str]
    alias_map: dict[str, str]

    def canonical(self, token: str) -> Optional[str]:
        """Canonicalize via the frozen alias map; an absent token rejects the row."""
        resolved = self.alias_map.get(token, token)
        if resolved in self.structure_methods or resolved in self.seq_methods:
            return resolved
        return None


def assign_provenance(row: DesignRow, root_backbone_id: str, structure_method: str) -> DesignRow:
    """Assigned at backbone-generation time and propagated unchanged downstream.

    One id per de novo backbone, shared by every derived sequence and every partial-
    diffusion variant -- which is what makes the per-backbone cap meaningful rather than
    a count of near-duplicates.
    """
    row.root_backbone_id = root_backbone_id
    row.structure_method = structure_method
    return row


def recompute_and_admit(row: DesignRow, vocab: MethodVocab, mask: Sequence[str],
                        stats: dict[str, tuple[float, float]]) -> DesignRow:
    """The writer recomputes every gate from the row's own sequence and structure.

    Admission requires agreement with the carried value to within 1e-4; a mismatch halts
    the writer with the row id rather than preferring either value. The row's carried
    numbers are treated as a claim to be checked, not as data.
    """
    if vocab.canonical(row.structure_method) is None:
        raise ValueError(f"{row.design_id}: structure_method not in frozen vocabulary")
    recomputed = {
        "novelty": novelty_gate(row),
        "liability": liability_gate(row),
        "monomer_foldability": monomer_foldability_gate(row),
        "structural_plausibility": structural_plausibility_gate(row),
    }
    for name, value in recomputed.items():
        if row.gates.get(name) != value:
            raise ValueError(f"{row.design_id}: gate {name} disagrees with carried value")
    if not scores_agree(row.pose_dockq, pose_dockq(row)):
        raise ValueError(f"{row.design_id}: pose_dockq disagrees with recompute")
    if not scores_agree(row.final_score, final_score(row, mask), AGREEMENT_TOL):
        raise ValueError(f"{row.design_id}: final_score disagrees with frozen-mask recompute")
    if not scores_agree(row.rank_zscore, rank_zscore(row, mask, stats)):
        raise ValueError(f"{row.design_id}: rank_zscore disagrees with recompute")
    return row


# @block st-181 kind=logic
def gate_recompute(row: DesignRow, thresholds: dict[str, float]) -> None:
    """At write time, recompute every gate at the SAME threshold the carried flag was
    set at. Any disagreement is fail-loud and blocks the row.

    Recomputing at a *different* threshold would produce disagreements that are not
    errors, which is why the threshold travels with the flag.
    """
    for name, carried in row.gates.items():
        fresh = _recompute_one(row, name, thresholds[name])
        if fresh != carried:
            raise ValueError(f"{row.design_id}: {name} recomputed {fresh}, carried {carried}")


def _recompute_one(row: DesignRow, gate: str, threshold: float) -> bool:
    if gate == "monomer_foldability":
        return monomer_foldability_gate(row, threshold=threshold)
    return bool(row.gates.get(gate, False))


# ── selection caps ────────────────────────────────────────────────────────────────────

# @block st-92 kind=logic
@dataclass(frozen=True)
class SelectionCaps:
    """Six ceilings, applied in selection order. Ceilings, not quotas.

    If the ranked pool cannot fill 30 rows under these, the fix is upstream -- more
    designs, more methods -- not a relaxation. The relaxation ladder in st-185 is the
    last resort, and it has its own floors.
    """

    levenshtein_min: int = 5             # (b) reject pairs closer than this
    per_root_backbone: float = 0.05      # (c) 5% of rows, rounded up
    per_tm90_cluster: float = 0.10       # (d) 10%, rounded up
    per_structure_method: float = 0.50   # (e) 50%, max 15 of 30
    min_structure_methods: int = MIN_DISTINCT_STRUCTURE_METHODS
    per_seq_method: float = 2 / 3        # (f) relaxed only as a last resort


def enforce_selection_caps(ranked: Sequence[DesignRow], n_rows: int = SHEET_ROWS_PER_TARGET,
                           caps: SelectionCaps = SelectionCaps()) -> list[DesignRow]:
    """Walk the ranked pool in order and admit a row only if every cap still holds.

    Enforcing by selection-order algorithm (rather than by a per-row PASS column) is the
    only way to get this right: diversity is a property of the SELECTED SET, so whether
    a row is admissible depends on what has already been admitted.
    """
    selected: list[DesignRow] = []
    ceil_root = math.ceil(caps.per_root_backbone * n_rows)
    ceil_clust = math.ceil(caps.per_tm90_cluster * n_rows)
    ceil_method = math.floor(caps.per_structure_method * n_rows)
    ceil_seq = math.floor(caps.per_seq_method * n_rows)

    for cand in ranked:
        if any(cand.sequence == s.sequence for s in selected):            # (a)
            continue
        if any(levenshtein(cand.sequence, s.sequence) < caps.levenshtein_min
               for s in selected):                                        # (b)
            continue
        if _count(selected, "root_backbone_id", cand.root_backbone_id) >= ceil_root:
            continue                                                      # (c)
        if _count(selected, "tm90_cluster_id", cand.tm90_cluster_id) >= ceil_clust:
            continue                                                      # (d)
        if _count(selected, "structure_method", cand.structure_method) >= ceil_method:
            continue                                                      # (e)
        if _count(selected, "seq_method", cand.seq_method) >= ceil_seq:
            continue                                                      # (f)
        selected.append(cand)
        if len(selected) == n_rows:
            break
    return selected


def _count(rows: Sequence[DesignRow], attr: str, value) -> int:
    return sum(1 for r in rows if getattr(r, attr) == value)


def distinct_structure_methods(rows: Sequence[DesignRow]) -> int:
    return len({r.structure_method for r in rows})


def levenshtein(a: str, b: str) -> int:
    """Edit distance, used by cap (b) and by the pre-order re-check."""
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# ── the schema ────────────────────────────────────────────────────────────────────────

# @block st-179 kind=schema
REQUIRED_COLUMNS = (
    "design_id", "target", "sequence", "binder_len", "rank", "rank_zscore",
    "final_score", "score_instrument", "pose_PASS", "pose_dockq", "structure_method",
    "seq_method", "opt_round", "root_backbone_id", "parent_design_id", "n_seeds",
    "novelty_verdict_path", "tm90_cluster_id", "fold_class", "designed_structure_path",
)


def sheet_schema(arms: Sequence[str] = RANKING_ARMS,
                 shadow_metrics: Sequence[str] = ("monomer_plddt", "lcp_score", "esmc_ll")):
    """Frozen at kickoff by the orchestrator; per-target writers validate against it.

    The merge script refuses sheets with renamed, retyped, missing or duplicated columns,
    which is what stops fourteen independently-written per-target sheets from drifting
    into fourteen incompatible schemas.
    """
    columns = list(REQUIRED_COLUMNS)
    columns += [f"predicted_structure_path_{a}" for a in arms]
    columns += [f"ipsae_{a}" for a in arms]
    columns += [f"sc_DockQ_{a}" for a in arms]
    columns += list(shadow_metrics)
    return {"columns": columns, "mandatory_nonnull": list(MANDATORY_NONNULL)}


# ── the null policy and rank assignment ───────────────────────────────────────────────

# @block st-180 kind=logic
MANDATORY_NONNULL = (
    "design_id", "target", "root_backbone_id", "structure_method", "rank",
    "rank_zscore", "final_score", "score_instrument", "pose_PASS", "pose_dockq",
    "designed_structure_path",
)


def rank_key(row: DesignRow):
    """The ONE rank-assignment path: full-seed tier, then pose, then score.

    A row below the seed protocol after a failed top-up is still RANKED, under a lower
    tier, with its seed count disclosed. The unranked section is reserved for rows with
    missing or zero scores -- a different failure entirely, and conflating the two would
    hide incomplete measurement behind an apparent quality judgement.
    """
    return (row.min_seeds >= SEEDS_FINAL, row.pose_PASS, row.rank_zscore)


def assign_ranks(rows: Sequence[DesignRow]) -> list[DesignRow]:
    ordered = sorted(rows, key=rank_key, reverse=True)
    for i, row in enumerate(ordered, start=1):
        row.rank = i
    return ordered


def write_score(value: Optional[float]) -> float:
    """A missing per-arm score is NaN. Never 0.0, -1, -999 or an empty string.

    A sentinel silently becomes a real number in a downstream mean; NaN does not.
    """
    return math.nan if value is None else value


def needs_seed_topup(row: DesignRow) -> bool:
    """DELIVERABLES dispatches one targeted top-up wave before sheet-freeze.

    Companion off-target and oligomer runs go with it so selectivity_delta and N:N stay
    seed-matched. These are audit re-scoring and are exempt from the close-out wave ban
    -- but never during a WATCHDOG halt.
    """
    return row.min_seeds < SEEDS_FINAL


def topup_allowed(governor_basis: str) -> bool:
    return governor_basis not in ("WATCHDOG_RUNAWAY", "DEAD_ORCHESTRATOR")


# ── the relaxation ladder ─────────────────────────────────────────────────────────────

# @block st-185 kind=logic
RELAXATION_ORDER = ("diversity_caps", "liability", "novelty_last_resort")

RELAXED_FLOORS = SelectionCaps(
    per_root_backbone=0.25,          # never past 25%
    per_structure_method=0.50,       # never past 50%
    min_structure_methods=3,         # never fewer than three
)

NEVER_RELAXED = ("pose_dockq_nonnull", "final_score_nonnull",
                 "no_identical_rows", "target_mimic_ban", "natural_copy_ban")


def reach_row_count(pool: Sequence[DesignRow], regenerated: bool) -> tuple[list[DesignRow], list[str]]:
    """Relax in this fixed order, one step at a time, recording which step admitted each row.

    Regeneration comes first and is not optional: the ladder is only entered after more
    designs and more methods have been tried. Novelty is last and stays bounded by the
    absolute floors, so even the last resort cannot ship a target mimic or a natural
    sequence copy.

    If even that cannot reach 30, ship the actual N. Padding with duplicates is forbidden.
    """
    assert regenerated, "regenerate upstream before entering the ladder"
    steps: list[str] = []
    selected = enforce_selection_caps(pool)
    if len(selected) < SHEET_ROWS_PER_TARGET:
        steps.append("diversity_caps")
        selected = enforce_selection_caps(pool, caps=RELAXED_FLOORS)
    if len(selected) < SHEET_ROWS_PER_TARGET:
        steps.append("liability")
        selected = enforce_selection_caps(
            [r for r in pool if r.gates.get("novelty")], caps=RELAXED_FLOORS)
    if len(selected) < SHEET_ROWS_PER_TARGET:
        steps.append("novelty_last_resort")
        for row in pool:
            row.relaxation_step = "NOVELTY_LAST_RESORT"
        selected = enforce_selection_caps(pool, caps=RELAXED_FLOORS)
    return selected, steps


def relax_by_configuration_only(writer_thresholds: dict, gate_predicates_touched: bool) -> None:
    """Relaxation changes the writer's configured thresholds -- never by deleting,
    commenting out, no-oping or monkeypatching a gate predicate.

    The distinction matters because a disabled predicate leaves no trace in the sheet,
    while a changed threshold is a disclosed number.
    """
    assert not gate_predicates_touched, "relaxation must be configuration, not surgery"


def assert_distinct_seeds(seeds: Sequence[int], n_seeds: int) -> None:
    """Seeds are DISTINCT integers per arm; a per-design std of 0 across n_seeds>1 is a
    bug, not a very reproducible design."""
    assert len(set(seeds)) == n_seeds, "seeds must be distinct"


# ── rank eligibility ──────────────────────────────────────────────────────────────────

# @block st-240 kind=logic
def route_row(row: DesignRow, required_gates: Sequence[str],
              topup_attempted: bool) -> tuple[str, Optional[str]]:
    """Ranked, or unranked with the reason named. Nothing ships unexplained.

    Seed-count alone never routes a row to unranked until a top-up has been tried and
    failed: a design a few seeds short of protocol is incomplete, not below-protocol.
    A gate that exists but was not run is a protocol violation, not a pass.
    """
    for gate in required_gates:
        if gate not in row.gates:
            return "unranked", f"missing gate result: {gate}"
        if not row.gates[gate]:
            return "unranked", f"gate failed: {gate}"
    for column in ("root_backbone_id", "structure_method", "tm90_cluster_id", "fold_class"):
        if getattr(row, column) is None:
            return "unranked", f"missing diversity column: {column}"
    if math.isnan(row.final_score) or row.final_score == 0:
        return "unranked", "missing or zero score"
    if math.isnan(row.pose_dockq):
        return "unranked", "pose check did not run"
    if row.min_seeds < SEEDS_FINAL and not topup_attempted:
        return "pending_topup", None
    return "ranked", None


def closing_check(rows: Sequence[DesignRow]) -> None:
    """No ranked row carries an empty or zero score. A deliverable that fails this does
    not ship until fixed, and a short list is never padded to depth."""
    bad = [r.design_id for r in rows
           if r.rank is not None and (math.isnan(r.final_score) or r.final_score == 0)]
    assert not bad, f"ranked rows with empty or zero score: {bad[:5]}"


# ── companions ────────────────────────────────────────────────────────────────────────

# @block st-183 kind=schema
PER_SEED_KEY = ("design_id", "scoring_arm", "seed")
COMPANION_SAMPLE_ROWS = 30


def assert_companion_coverage(sheet: Sequence[DesignRow], companion_ids: set[str]) -> None:
    """Companion design_ids cover 100% of ranked design_ids, exact and case-sensitive.

    The companion exists so any sheet score can be reproduced without re-compute, which
    only works if the coverage is total; anything less is a deliverable defect.
    """
    missing = {r.design_id for r in sheet} - companion_ids
    assert not missing, f"per_seed_metrics missing {len(missing)} ranked design_ids"


def verify_scores_from_companion(sample: Sequence[DesignRow], mask: Sequence[str],
                                 recompute_from_companion) -> None:
    """Recompute final_score for 30 sampled rows per target from the companion ALONE,
    using the pre-registered formula. Agreement within 1e-4 or the companion is
    regenerated."""
    for row in sample:
        if not scores_agree(row.final_score, recompute_from_companion(row, mask)):
            raise ValueError(f"{row.design_id}: companion disagrees with sheet")


# @block st-184 kind=schema
@dataclass
class InstrumentRealization:
    """One row per (target, ranking_arm): what the instrument actually turned out to be.

    Every numeric here is DERIVED from per_seed_metrics.parquet and the gate file at
    write time, never hand-authored. The report's scoring section is generated from this
    table, so a target whose realized instrument differs from the campaign default gets
    called out rather than quietly averaged in.
    """

    target: str
    arm_name: str
    gate_status: str
    n_seeds_run: int
    n_ranked_with_score: int
    used_in_final_score: bool
    control_separation_value: Optional[float]
    drop_reason: str
    cofactors_present: tuple[str, ...]
    n_target_chains_folded: int
    native_oligomer_n: int


def assert_realization_consistent(rows: Sequence[InstrumentRealization]) -> None:
    for r in rows:
        if r.gate_status == "PASS" and r.control_separation_value is None:
            assert r.drop_reason, "no-literature-control path must be named in drop_reason"
        if not r.used_in_final_score:
            assert r.drop_reason, f"{r.target}/{r.arm_name}: drop_reason required"


# ── the pre-order re-check ────────────────────────────────────────────────────────────

# @block st-246 kind=logic
SELECTIVITY_TERMS_PER_ARM = 1     # extends the six-term score to nine on counter-screens


def preorder_recheck(selected: Sequence[DesignRow], threshold: float,
                     caps: SelectionCaps = SelectionCaps()) -> None:
    """Everything the gates already checked, run again on the final selected set.

    The re-check is not redundant: the caps are a property of the selected set, and the
    set is only final now. This is the last point at which a defect is cheaper to fix
    than to explain.
    """
    n = len(selected)
    assert len({r.sequence for r in selected}) == n, "exact-duplicate sequences"
    for i, a in enumerate(selected):
        for b in selected[i + 1:]:
            assert levenshtein(a.sequence, b.sequence) >= caps.levenshtein_min
    assert all(_count(selected, "root_backbone_id", r.root_backbone_id)
               <= math.ceil(caps.per_root_backbone * n) for r in selected)
    assert all(_count(selected, "tm90_cluster_id", r.tm90_cluster_id)
               <= math.ceil(caps.per_tm90_cluster * n) for r in selected)
    assert distinct_structure_methods(selected) >= caps.min_structure_methods


def selectivity_delta(on_target_ipsae: float, off_target_ipsae: float) -> float:
    """Per arm, under the SAME seed count and aggregation as that on-target arm.

    An instrument-mismatched subtraction is invalid: subtracting a 1-seed off-target
    score from a 5-seed on-target score measures the seed count, not the selectivity.
    """
    return on_target_ipsae - off_target_ipsae


def selectivity_score_terms(row: DesignRow, mask: Sequence[str],
                            deltas: dict[str, float]) -> list[tuple[str, float]]:
    """Six terms become nine on a counter-screened target, each delta carrying the ipSAE
    weight of 4 in rank_zscore. On-target, off-target and selectivity are all recorded as
    their own columns regardless."""
    return [(f"selectivity_delta_{a}", deltas.get(a, math.nan)) for a in mask]


def assert_counter_screen_complete(rows: Sequence[DesignRow], deltas: dict[str, dict]) -> None:
    """A null off-target or selectivity value on any ranked row of a counter-screened
    target is a sheet-writer fail-loud, not a documented gap. All 30 rows must have run
    the counter-screen before the sheet is canonical."""
    for row in rows:
        d = deltas.get(row.design_id, {})
        assert d and not any(math.isnan(v) for v in d.values()), \
            f"{row.design_id}: counter-screen incomplete"
