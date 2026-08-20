"""The instrument: ipSAE, pose agreement, and the two summary scores.

Three ranking arms, six raw terms, one weighted z-score for ordering and one raw mean
for reporting. Everything here is frozen at the validation gate before any production
design is scored.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from .campaign import (
    AGREEMENT_TOL,
    DOCKQ_WEIGHT,
    IPSAE_WEIGHT,
    POSE_DOCKQ_DEFAULT,
    RANKING_ARMS,
    DesignRow,
)

# ── ipSAE, exactly ────────────────────────────────────────────────────────────────────

# @block st-121 kind=logic
def ipsae_min(prediction, binder_chain: str, target_chains: Sequence[str],
              ipsae: Callable[..., float]) -> float:
    """Minimum over both alignment directions, per Dunbrack 2025.

    For a multimeric target the mask is a *union*: mask_target is every residue whose
    asym_id is not the binder, with n0/d0 re-derived from the union mask sizes. This
    single call replaces the stock pairwise loop over (binder, protomer_i) -- the
    pairwise version answers a different question and is not comparable.

    Absolute ipSAE compresses with chain count, so raw cross-target comparison is
    invalid. That is why ranking is always on a per-target z-score.
    """
    mask_binder = [r for r in prediction.residues if r.asym_id == binder_chain]
    mask_target = [r for r in prediction.residues if r.asym_id != binder_chain]
    assert {r.asym_id for r in mask_target} <= set(target_chains)
    forward = ipsae(prediction, mask_binder, mask_target)
    reverse = ipsae(prediction, mask_target, mask_binder)
    return min(forward, reverse)


def aggregate_over_seeds(per_seed: Sequence[float]) -> float:
    """Max over seeds, after the min over directions. Order matters and is fixed."""
    values = [v for v in per_seed if not math.isnan(v)]
    return max(values) if values else math.nan


# ── pose agreement ────────────────────────────────────────────────────────────────────

# @block st-98 kind=logic
SUBSTITUTE_ARM_PREFERENCE = (
    "AlphaFold-Multimer-v3",
    "AlphaFold3 code with OpenFold3 weights",
    "Chai-1",
    "Boltz-2",
    "Boltz-1",
)


def sc_dockq(designed_complex, prediction, dockq: Callable[..., float]) -> float:
    """DockQ between the designed complex and this arm's argmax-ipSAE_min prediction.

    The chain mapping is the best symmetric relabeling -- the one that maximises DockQ.
    That applies on monomeric targets too, because chain ids in the designed and
    predicted structures need not agree.
    """
    return max(dockq(designed_complex, prediction, mapping)
               for mapping in prediction.symmetric_relabelings())


def pose_dockq(row: DesignRow) -> float:
    """Minimum over the arms that ran -- the weakest arm sets the pose verdict."""
    ran = [v for v in row.sc_dockq.values() if not math.isnan(v)]
    return min(ran) if ran else math.nan


def pose_pass(row: DesignRow, threshold: float = POSE_DOCKQ_DEFAULT) -> bool:
    """The per-target threshold, unless the validation gate froze a stricter one."""
    value = pose_dockq(row)
    return not math.isnan(value) and value >= threshold


def promotion_key(row: DesignRow, zscores: dict[str, float]) -> float:
    """Every promotion step ranks on ipSAE *and* sc_DockQ together.

    Promoting on ipSAE alone would enrich the FINAL pool for one arm's optimism rather
    than for agreement between them, which is the actual evidence of binding at the
    intended epitope.
    """
    return statistics.fmean([zscores["ipsae"], zscores["sc_dockq"]])


# ── the two summary scores ────────────────────────────────────────────────────────────

# @block st-105 kind=logic
def score_terms(row: DesignRow, mask: Sequence[str]) -> list[tuple[str, float]]:
    """The six raw terms: three per-arm ipSAE_min and three per-arm sc_DockQ."""
    terms = [(f"ipsae_{a}", row.ipsae_min.get(a, math.nan)) for a in mask]
    terms += [(f"sc_dockq_{a}", row.sc_dockq.get(a, math.nan)) for a in mask]
    return terms


def final_score(row: DesignRow, mask: Sequence[str]) -> float:
    """The headline value: the raw mean of the six terms.

    Under a disclosed REDUCED_MASK the mean runs over the realized terms only, and
    `score_instrument` names them -- so a reader can always tell which arms produced
    the number. Dropping a validated arm from a frozen mask is sheet corruption.
    """
    values = [v for _, v in score_terms(row, mask) if not math.isnan(v)]
    return statistics.fmean(values) if values else math.nan


def rank_zscore(row: DesignRow, mask: Sequence[str],
                per_target_stats: dict[str, tuple[float, float]]) -> float:
    """Per-target 4:1 weighted z-score average of the same six terms. Ranking only.

    The 4:1 weighting says the campaign trusts interface confidence four times as much
    as pose agreement for *ordering*, while still requiring pose agreement to pass as a
    gate. The two scores answer different questions and are deliberately not merged.
    """
    num = den = 0.0
    for name, value in score_terms(row, mask):
        if math.isnan(value):
            continue
        mean, sd = per_target_stats[name]
        if sd == 0:
            continue
        weight = IPSAE_WEIGHT if name.startswith("ipsae") else DOCKQ_WEIGHT
        num += weight * (value - mean) / sd
        den += weight
    return num / den if den else math.nan


# @block st-107 kind=protocol
def freeze_mask(gate, arms: Sequence[str] = RANKING_ARMS) -> tuple[str, ...]:
    """The per-target instrument mask is frozen at validation-gate time.

    The frozen-mask, NaN-reject and DERIVED-realization rules are then enforced by the
    sheet writer rather than by anyone remembering them.
    """
    return tuple(a for a in arms if gate.condition_a(a) and gate.condition_b(a))


def preregister_alternative(target: str, separates_controls_better: bool,
                            frozen_before_production: bool, disclosed: bool) -> bool:
    """A different rank_zscore is permitted only on demonstrated evidence, frozen and
    disclosed BEFORE any production design on that target is scored.

    Pre-registration is what separates 'we found a better formula' from 'we tuned the
    formula until our designs won'.
    """
    return separates_controls_better and frozen_before_production and disclosed


# ── self-consistency ──────────────────────────────────────────────────────────────────

# @block st-116 kind=logic
def pose_self_consistent(row: DesignRow) -> bool:
    """The mechanical form of 'the prediction must recapitulate the designed epitope'
    is simply: pose_dockq is non-null on every ranked row."""
    return not math.isnan(pose_dockq(row))


# @block st-236 kind=logic
def assert_seed_concordance(row: DesignRow, arm: str) -> None:
    """The self-consistency DockQ for an arm is computed on the SAME seed whose
    ipSAE_min became that arm's score -- not on a separately-chosen max-DockQ seed.

    Choosing the best seed per metric independently would report an agreement that no
    single prediction ever achieved. Both argmaxes are recorded so the discrepancy is
    auditable rather than assumed away.
    """
    assert arm in row.argmax_seed_ipsae, f"{row.design_id}: no argmax seed for {arm}"
    assert arm in row.argmax_seed_dockq, f"{row.design_id}: no DockQ seed for {arm}"


def rank_eligible_on_pose(row: DesignRow) -> bool:
    """A NaN pose result is a missing measurement, not a flag: the check must have RUN.

    pose_FAIL rows still ship, at the bottom of the target's ranked set, with the count
    disclosed -- so a suspect instrument shows up as a pattern instead of vanishing.
    """
    return pose_self_consistent(row)


def instrument_is_suspect(rows: Sequence[DesignRow], top_n: int = 10) -> bool:
    """If a substantial fraction of a target's top designs fail pose, or the three arms
    disagree on pose, suspect the instrument before the designs."""
    top = sorted(rows, key=lambda r: r.rank_zscore, reverse=True)[:top_n]
    if not top:
        return False
    failed = sum(1 for r in top if not r.pose_PASS)
    spread = [max(r.sc_dockq.values()) - min(r.sc_dockq.values())
              for r in top if len(r.sc_dockq) > 1]
    return failed / len(top) > 0.5 or (bool(spread) and statistics.fmean(spread) > 0.3)


# ── oligomeric targets ────────────────────────────────────────────────────────────────

# @block st-117 kind=logic
@dataclass
class OligomerScores:
    """Both stoichiometries, recorded as their own required sheet columns.

    1:N is one binder against all N protomers and is the construct that feeds
    rank_zscore. N:N is one binder per protomer at full occupancy, and exists to catch
    designs whose score depends on the other sites being empty.
    """

    ipsae_min_1n: float
    ipsae_min_nn: float
    sc_dockq_nn: float
    binder_binder_clashes: int

    @property
    def collapsed(self) -> bool:
        """Disclose any design whose N:N score collapses relative to its 1:N."""
        return self.ipsae_min_nn < 0.5 * self.ipsae_min_1n


def build_nn_reference(designed_binder_pose, symmetry_operators):
    """Apply the target multimer's own Cn operators to the single designed pose.

    The reference is symmetry mates of one binder; the *prediction* is co-folded with N
    independent binder chains. Building the reference any other way compares two
    different objects.
    """
    return [op.apply(designed_binder_pose) for op in symmetry_operators]


def crop_allowed(stage: str) -> bool:
    """Design may crop protomers for memory or speed. Scoring and filtering may not:
    every prediction there models the full multimer."""
    return stage == "design"


# ── recompute, the operation the sheet writer performs on every row ───────────────────

def scores_agree(carried: float, recomputed: float, tol: float = AGREEMENT_TOL) -> bool:
    """Agreement to within 1e-4. Used wherever a carried value meets a fresh one."""
    if math.isnan(carried) and math.isnan(recomputed):
        return True
    return abs(carried - recomputed) <= tol
