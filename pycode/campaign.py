"""Shared vocabulary for the campaign's mechanical clauses.

This package is a reconstruction. The prompt states these rules in prose; this is what
that prose says when written as code. It is not the campaign's implementation and it
calls no real service -- `external.py` stubs the provider surface so the modules import
cleanly and the pure logic can be exercised by `selftest.py`.

Regions carried by the viewer are marked `# @block st-<line> kind=<kind>`, where
st-<line> is the prompt line the region encodes. Kinds:

    logic     an algorithm: thresholds, ordering, arithmetic, control flow
    schema    a frozen data shape (columns, dtypes, required keys)
    config    a pinned recipe -- flags, versions, paths; code only in the sense that
              it is machine-readable and frozen
    protocol  a contract between agents: who may write what, in what order
    lint      a rule about the campaign's own source, checkable statically
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# ── campaign scalars ──────────────────────────────────────────────────────────────────
# The multi-target prompt is this same document with these values rescaled; every
# other name in this package is byte-identical between the two campaigns.

BUDGET_USD = 10_000
WALL_CLOCK_HOURS = 24
TARGET_HOURLY_RATE = BUDGET_USD / WALL_CLOCK_HOURS      # $417/h
BOOTSTRAP_CEILING = 150
BOOTSTRAP_STEP = 25
DAEMON_LIMIT_MAX = 200
SUBAGENT_HEADROOM_MAX = 50
CLOSE_OUT_RESERVE_HOURS = 1
STALE_METERED_USD = 40

# ── the instrument ────────────────────────────────────────────────────────────────────

RANKING_ARMS = ("ef2full", "ef2fast", "ptxv2")
IPSAE_WEIGHT = 4
DOCKQ_WEIGHT = 1
POSE_DOCKQ_DEFAULT = 0.23
MONOMER_PLDDT_DEFAULT = 70.0            # on the 0-100 scale; ESMFold2 emits 0-1
AGREEMENT_TOL = 1e-4                    # recompute-vs-carried tolerance, everywhere

SHEET_ROWS_PER_TARGET = 30
SEEDS_FINAL = 5
METHOD_FLOOR_BACKBONES = 50
MIN_DISTINCT_STRUCTURE_METHODS = 3

STATE = "/state"
LEDGER = "/ledger"


# ── the row that every downstream rule is about ───────────────────────────────────────

@dataclass
class DesignRow:
    """One candidate binder, as it travels from generation to the shipped sheet.

    The field set is the schema's required columns (st-179); per-arm score columns are
    held in dicts keyed by arm rather than flattened, so `sc_dockq["ptxv2"]` here is
    `sc_DockQ_ptxv2` in the CSV.
    """

    design_id: str
    target: str
    sequence: str
    designed_structure_path: str

    # provenance, assigned at backbone-generation time and never rewritten (st-90)
    root_backbone_id: str
    structure_method: str
    seq_method: Optional[str] = None
    parent_design_id: Optional[str] = None
    opt_round: int = 0

    # per-arm raw metrics; NaN means "this arm did not run", never 0.0 (st-180)
    ipsae_min: dict[str, float] = field(default_factory=dict)
    sc_dockq: dict[str, float] = field(default_factory=dict)
    predicted_structure_path: dict[str, str] = field(default_factory=dict)
    n_seeds: dict[str, int] = field(default_factory=dict)
    argmax_seed_ipsae: dict[str, int] = field(default_factory=dict)
    argmax_seed_dockq: dict[str, int] = field(default_factory=dict)

    # gate verdicts, recomputed by the writer before the row is admitted (st-181)
    gates: dict[str, bool] = field(default_factory=dict)

    # summary scores
    final_score: float = math.nan
    rank_zscore: float = math.nan
    score_instrument: str = ""
    pose_dockq: float = math.nan
    pose_PASS: bool = False

    # diversity keys the caps are computed over (st-92, st-240)
    tm90_cluster_id: Optional[str] = None
    fold_class: Optional[str] = None

    rank: Optional[int] = None
    relaxation_step: Optional[str] = None

    @property
    def binder_len(self) -> int:
        return len(self.sequence)

    @property
    def min_seeds(self) -> int:
        """Seed count on the *weakest* arm -- the tier the rank key sorts on."""
        return min(self.n_seeds.values()) if self.n_seeds else 0


# ── the biology gate that precedes all compute ────────────────────────────────────────

# @block st-39 kind=logic
@dataclass(frozen=True)
class TargetDossier:
    """The literature record a target must have before any design or scoring runs.

    Recorded in the design sheet's target metadata, and frozen alongside the instrument
    mask at gate time. The point of freezing it is the assertion below: a scoring job
    can then check what it actually folded against what the campaign said it would.
    """

    target: str
    oligomeric_state: int                 # protomers at assay conditions
    cofactors: tuple[str, ...]            # metals, nucleic acids, glycans
    cofactor_required: bool               # fold- or interface-required per literature
    assay_construct: str                  # residue range, tags, fusion context
    epitope_ordered_structures: tuple[str, ...]
    prior_difficulty: float               # feeds the per-target budget share (st-158)


@dataclass(frozen=True)
class ScoringConstruct:
    """Per-arm construct, frozen at gate time and identical at every seed tier."""

    arm: str
    n_target_chains: int
    cofactor_atoms: int
    crop: str


def assert_construct_realized(frozen: ScoringConstruct, observed: ScoringConstruct) -> str:
    """Compare what an arm asserted against what its own output structure contains.

    Called by the scoring job on its own output, at the validation gate AND on every
    production row -- not by trusting the input script's intent. A mismatch writes the
    score as NaN with this status, never as a number.
    """
    if (observed.n_target_chains != frozen.n_target_chains
            or observed.cofactor_atoms != frozen.cofactor_atoms):
        return "CONSTRUCT_FAIL"
    return "OK"


def dossier_satisfied_by(dossier: TargetDossier, constructs: list[ScoringConstruct]) -> bool:
    """At least one ranking arm must represent a fold- or interface-required cofactor."""
    if not dossier.cofactor_required:
        return True
    return any(c.cofactor_atoms > 0 for c in constructs)
