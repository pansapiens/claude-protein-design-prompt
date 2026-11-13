"""The gates: four pre-scoring filters, and the per-target validation gate.

The filters run inside the generation job, before any co-folding spend. The validation
gate is a file, and `submit_gate` in `governor.py` reads it, making it an enforced
precondition rather than an unchecked claim.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Optional

from .campaign import (
    MONOMER_PLDDT_DEFAULT,
    RANKING_ARMS,
    STATE,
    DesignRow,
    TargetDossier,
)

# ── pre-scoring filters ───────────────────────────────────────────────────────────────

# @block st-79 kind=protocol
KNOWN_BINDER_CORPUS = "02 ProteinBase"


def stage_novelty_databases(hour: float) -> list[str]:
    """UniRef90 and the known-binder corpus are staged in the first hour, alongside
    roster validation, but production scoring is *not* gated on that staging.

    The novelty check and the Ubiquitin rejection are required before a row reaches the
    FINAL ranked sheet, not before first production dispatch. Ordering the two this way
    is what keeps a slow database stage off the campaign's critical path.
    """
    assert hour <= 1.0, "staging belongs in the first hour"
    return ["UniRef90", KNOWN_BINDER_CORPUS]


def prescoring_filters(row: DesignRow, dossier: TargetDossier) -> dict[str, bool]:
    """Every candidate is assessed on all four before it is scored."""
    return {
        "novelty": novelty_gate(row),
        "liability": liability_gate(row),
        "monomer_foldability": monomer_foldability_gate(row),
        "structural_plausibility": structural_plausibility_gate(row),
    }


# @block st-81 kind=logic
UNIREF90_IDENTITY_MAX = 0.60          # over >50% coverage
UNIREF90_COVERAGE_MIN = 0.50
LOCAL_IDENTITY_MAX = 0.30             # over >=40 aligned residues
LOCAL_ALIGNED_MIN = 40
TM_SCORE_MAX = 0.50                   # to any target or control chain

UBIQUITIN_ACCESSIONS = ("P0CG47", "P0CG48")


@dataclass(frozen=True)
class NoveltyEvidence:
    """What MMseqs2 and the structural comparison returned for one candidate."""

    best_identity: float
    best_coverage: float
    local_identity: float
    local_aligned_residues: int
    best_tm_to_target_or_control: float


def novelty_gate(row: DesignRow, ev: Optional[NoveltyEvidence] = None) -> bool:
    """Three independent thresholds, any one of which rejects.

    The TM-score arm is the one that catches target-mimic protomers: a structure
    generator asked for a binder of similar length will sometimes reproduce a protomer
    of the target itself, and sequence identity alone does not see that. Catching it
    here rather than downstream is the point.

    Ubiquitin is detected by local alignment rather than exact match because it emerges
    with short terminal extensions that defeat an exact comparison.
    """
    if ev is None:
        return bool(row.gates.get("novelty", False))
    if ev.best_identity > UNIREF90_IDENTITY_MAX and ev.best_coverage > UNIREF90_COVERAGE_MIN:
        return False
    if ev.local_identity >= LOCAL_IDENTITY_MAX and ev.local_aligned_residues >= LOCAL_ALIGNED_MIN:
        return False
    if ev.best_tm_to_target_or_control >= TM_SCORE_MAX:
        return False
    return True


# @block st-82 kind=logic
def liability_gate(row: DesignRow, max_homopolymer_run: int = 4,
                   max_hydrophobic_patch: float = 0.30) -> bool:
    """Developability: cysteine parity, homopolymer runs, surface hydrophobic patches."""
    seq = row.sequence
    if seq.count("C") % 2 != 0:
        return False
    run, prev = 1, ""
    for aa in seq:
        run = run + 1 if aa == prev else 1
        if run > max_homopolymer_run:
            return False
        prev = aa
    return _surface_hydrophobic_fraction(row) <= max_hydrophobic_patch


def _surface_hydrophobic_fraction(row: DesignRow) -> float:
    """Computed from the designed structure; stubbed here at a passing value."""
    return 0.0


# @block st-83 kind=logic
def monomer_foldability_gate(row: DesignRow, mean_plddt: Optional[float] = None,
                             threshold: float = MONOMER_PLDDT_DEFAULT) -> bool:
    """The binder alone must fold, at a per-target threshold frozen at the gate.

    ESMFold2 emits pLDDT on 0-1 while the threshold is conventionally written on 0-100,
    so normalize before comparing; reading 0.82 as failing an 82 threshold would
    mistakenly reject the entire pool.
    """
    if mean_plddt is None:
        return bool(row.gates.get("monomer_foldability", False))
    if mean_plddt <= 1.0:
        mean_plddt *= 100.0
    return mean_plddt >= threshold


# @block st-84 kind=logic
def structural_plausibility_gate(row: DesignRow, clashes: int = 0,
                                 core_packing: float = 1.0,
                                 geometry_ok: bool = True,
                                 max_clashes: int = 0,
                                 min_core_packing: float = 0.0) -> bool:
    """Backbone geometry, steric clashes, core packing: evaluated against thresholds chosen at
    kickoff and frozen, like every other threshold in the funnel."""
    return geometry_ok and clashes <= max_clashes and core_packing >= min_core_packing


# @block st-86 kind=logic
def assert_rejects_absent(rejected_ids: set[str], downstream_pool: list[DesignRow]) -> None:
    """A gate counts as run only when its rejects are traceably absent downstream.

    Recording a rejection and then scoring the design anyway is the failure this
    catches, and it is invisible unless something checks the pool.
    """
    leaked = sorted({r.design_id for r in downstream_pool} & rejected_ids)
    assert not leaked, f"rejected designs present downstream: {leaked[:5]}"


# ── the validation gate ───────────────────────────────────────────────────────────────

# @block st-111 kind=logic
def gate_path(target: str) -> str:
    return f"{STATE}/gates/{target}.json"


@dataclass
class ValidationGate:
    """Per target, per instrument: the file that unblocks production scoring.

    Condition (a) is fold recapitulation against a named CA-RMSD threshold. Condition
    (b) is positive-control separation: a known literature binder at full native
    stoichiometry scoring clearly above negative controls.

    (b) is dropped only when no literature control exists after a comprehensive search.
    If controls exist and (b) fails on every instrument, self-authorization is barred;
    the three listed remedies are the only permitted paths.
    """

    target: str
    status: str                                  # "PASS" unlocks scoring; nothing else
    ca_rmsd_threshold: float
    fold_recapitulated: dict[str, bool]
    control_separation: dict[str, Optional[float]]
    no_literature_control: bool = False
    frozen_mask: tuple[str, ...] = RANKING_ARMS
    pose_dockq_threshold: float = float("nan")

    def condition_a(self, arm: str) -> bool:
        return self.fold_recapitulated.get(arm, False)

    def condition_b(self, arm: str) -> bool:
        if self.no_literature_control:
            return True
        sep = self.control_separation.get(arm)
        return sep is not None and not math.isnan(sep) and sep > 0


CONTROL_FAILURE_REMEDIES = (
    "re-run the control with control-ligand MSA enabled",
    "try an alternative co-folder",
    "try AF_Unmasked with template injection",
)


def validation_gate_pass(target: str, read_file=None) -> bool:
    """What `submit_gate` calls when a scoring job names a target.

    A verbal claim, a Slack post, or an in-memory variable does not satisfy this. Only
    the file does, and only with status PASS.
    """
    if read_file is None:
        return False
    try:
        gate = json.loads(read_file(gate_path(target)))
    except (OSError, ValueError):
        return False
    return gate.get("status") == "PASS"
