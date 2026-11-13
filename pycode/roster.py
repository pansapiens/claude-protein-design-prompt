"""Tool bring-up: pinned recipes, the roster PASS predicate, and sandbox lifetime.

Nothing in the campaign may dispatch a method that does not have a PASS row here, so
this module is upstream of everything in `gates` and `scoring`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .campaign import LEDGER, STATE
from .external import modal, slack

# ── pinned recipes ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolRecipe:
    """An install + invocation recipe derived from the project's own README or card.

    Frozen at bring-up: production dispatch uses exactly the `image_id` this recipe
    produced, and any change to image or flags re-runs the check (st-230).
    """

    name: str
    source: str
    install: tuple[str, ...]
    weights: Optional[str] = None
    invoke: tuple[str, ...] = ()
    params: dict[str, object] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    canary_timeout_s: int = 600
    is_instrument_backbone: bool = False
    notes: tuple[str, ...] = ()


# @block st-53 kind=config
ESMFOLD2 = ToolRecipe(
    name="ESMFold2",
    source="https://github.com/Biohub/esm",
    install=("python3.12 -m pip install git+https://github.com/Biohub/esm",),
    weights="biohub/ESMFold2",              # ungated, MIT; -Fast variant is a sibling
    params={
        "num_loops": 10,
        "num_sampling_steps": 68,
        "num_diffusion_samples": 1,
        "blind": True,
        "msa_max_seq": 2048,                # Full only; Fast has no MSA encoder
    },
    is_instrument_backbone=True,
    notes=(
        "The PyPI package named 'esm' is a different project and lacks ESMFold2.",
        "Fast is single-sequence only: its checkpoint has no MSA encoder.",
        "Original ESMFold is superseded. Pre-AlphaFold3 folders in scope are "
        "AlphaFold2, AlphaFold-Multimer and their reproductions (ColabFold, OpenFold).",
    ),
)


def bringup_or_halt(recipe: ToolRecipe) -> None:
    """An instrument backbone that will not come up stops the campaign, loudly."""
    if not recipe.is_instrument_backbone:
        return
    slack.post(f"{recipe.name} bring-up failed; halting.")
    raise SystemExit(1)


# @block st-54 kind=config
PROTENIX_V2 = ToolRecipe(
    name="Protenix v2",
    source="https://github.com/bytedance/Protenix",
    install=("FROM nvidia/cuda:12.4-devel", "pip install protenix==2.0.0"),
    weights="https://huggingface.co/TMF001/pxdesign-weights",
    invoke=(
        "protenix pred --input in.json --model_name protenix-v2 --seeds N "
        "--cycle 10 --need_atom_confidence true --use_msa true",
    ),
    env={
        # First call JIT-compiles a CUDA layer-norm kernel (~4-6 min on H100). Point
        # this at a persistent state-volume path shared across containers so a retry
        # uses the cached extension instead of repeating the compile.
        "TORCH_EXTENSIONS_DIR": f"{STATE}/torch_extensions",
        "PROTENIX_ROOT_DIR": f"{STATE}/protenix",
    },
    canary_timeout_s=15 * 60,
    is_instrument_backbone=True,
    notes=(
        "Do not pass --step or --dtype; CLI defaults are 200 diffusion steps, bf16.",
        "v2.0.0 uses --use_msa, not --use_msa_server.",
        "Per-token PAE requires --need_atom_confidence true.",
        "Build the image fresh this campaign from the pinned recipe; a prebuilt or "
        "inherited image is ineligible.",
    ),
)

PROTENIX_CANARY_ATTEMPTS = 5


def protenix_bringup(attempt_canary) -> bool:
    """Hold production on every target until Protenix v2 reaches roster PASS.

    Each attempt gets the full timeout in a new container, because a fresh container is
    a different physical host with high probability. Bring-up of the other models
    continues while this is held.
    """
    for _ in range(PROTENIX_CANARY_ATTEMPTS):
        if attempt_canary(PROTENIX_V2.canary_timeout_s):
            return True
    bringup_or_halt(PROTENIX_V2)
    return False


# ── the bring-up stage and the sandbox contract ───────────────────────────────────────

# @block st-57 kind=protocol
TOOL_BRINGUP_MINUTES = 60
NON_MODEL_BRINGUP = ("ipSAE", "MMseqs2", "DockQ")


def run_in_sandbox(spec, harvest):
    """Every direct `modal.Sandbox.create()` path owns its sandbox's whole lifetime.

    try/finally with terminate() in the finally block, immediately after harvesting.
    Sandboxes left to idle to their timeout incur unmonitored charges.
    """
    sb = modal.Sandbox.create(spec)
    try:
        return harvest(sb)
    finally:
        sb.terminate()


def monitor_on_compute_done(event) -> str:
    """The per-10-jobs monitor owns termination for jobs dispatched via `host.compute`,
    where the campaign code never holds a sandbox handle.

    A non-zero exit code that nevertheless wrote its declared output is a HARVEST case,
    not a re-run case: ingest the on-disk results before deciding anything about retry.
    """
    if event.status == "success":
        modal.Sandbox.from_id(event.sandbox_id).terminate()
        return "TERMINATED"
    if event.wrote_declared_output:
        return "HARVEST"
    return "RETRY"


# ── the roster ledger ─────────────────────────────────────────────────────────────────

# @block st-230 kind=logic
@dataclass
class RosterRow:
    """One model or tool, as recorded in the single shared model-roster ledger."""

    model: str
    image_id: str
    weights_sha256: str
    gpu_type: str
    seconds_per_design: float
    usd_per_design: float
    wall_clock_s: float
    output_sha256: tuple[str, ...]
    validated_at: str
    status: str = "PENDING"


def roster_pass(
    container_builds: bool,
    weights_checksum_matches: bool,
    end_to_end_exit_code: int,
    n_designs: int,
    parsed_structures: int,
    sequences_emitted: int,
) -> bool:
    """All five conditions, on a campaign target, in the production image and flags.

    A toy peptide does not qualify, and neither does a different image: the whole point
    of the check is that `image_id` recorded here is the one production dispatches.
    """
    return (
        container_builds                                     # (1) builds and imports
        and weights_checksum_matches                         # (2) upstream release
        and end_to_end_exit_code == 0 and 2 <= n_designs <= 4  # (3) one real run
        and parsed_structures >= n_designs                   # (4) parseable outputs
        and sequences_emitted >= 1                           # (5) adapter consumes one
    )


REAP_WALL_CLOCK_MULTIPLE = 2.0
TERMINAL_STATUSES = ("success", "failed", "timed_out", "canceled")


def may_reap(job_status: str, lifetime_s: float, benchmarked_p90_s: float,
             job_id_in_ledger: bool) -> bool:
    """The only reap criterion campaign-wide. Idleness heuristics are not grounds.

    Also the subtractive term in `submit_gate` step (e): a sandbox that qualifies here
    is excluded from the live count.
    """
    if not job_id_in_ledger:
        return False
    if job_status in TERMINAL_STATUSES:
        return True
    return lifetime_s > REAP_WALL_CLOCK_MULTIPLE * benchmarked_p90_s


def job_metadata_path(launching_frame_id: str) -> str:
    """One file per launching frame; never a single shared file.

    The submitter appends here immediately after `submit_gate()` returns True, on every
    dispatch path. A dispatch path that cannot append to this ledger does not dispatch.
    """
    return f"{LEDGER}/job_metadata/{launching_frame_id}.jsonl"


CANARY_BEFORE_FANOUT = 10           # any fan-out above this is preceded by one canary
MAX_BUDGET_SHARE_PER_MODEL = 0.10   # until every roster model has passed or dropped


def timeout_for(benchmarked_p90_s: float) -> int:
    """The damage bound the provider itself enforces by killing the container.

    A method whose p90 exceeds 2700s fits by lowering its per-job batch size, not by
    raising this.
    """
    return min(math.ceil(REAP_WALL_CLOCK_MULTIPLE * benchmarked_p90_s), 5400)
