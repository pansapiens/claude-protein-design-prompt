"""The org chart: what the orchestrator may not do, and who catches it when it stops.

The through-line is that the orchestrator is treated as the least reliable component.
It holds no state, calls no SDK, never sleeps, and is watched by a singleton that can
halt the whole campaign without its cooperation.
"""

from __future__ import annotations

import ast
import time
from dataclasses import dataclass
from typing import Optional, Sequence

from .campaign import (
    DAEMON_LIMIT_MAX,
    METHOD_FLOOR_BACKBONES,
    STATE,
    SUBAGENT_HEADROOM_MAX,
)
from .external import host, modal, slack
from .governor import GOVERNOR_PATH, Governor, count_live_gpu_sandboxes, submit_gate

# ── the method floor ──────────────────────────────────────────────────────────────────

# @block st-65 kind=logic
FLOOR_MATRIX_PATH = f"{STATE}/floor_matrix.json"
FLOOR_CYCLE_MINUTES = 15


def floor_matrix(ledger_rows, targets: Sequence[str],
                 asterisked_methods: Sequence[str]) -> dict[tuple[str, str], int]:
    """The (target, method) structure-count matrix, recomputed every governor cycle.

    Every cell below the floor is an open obligation, and a missing matrix is itself a
    deviation; failing to compute it cannot pass as having nothing to do.
    """
    matrix = {(t, m): 0 for t in targets for m in asterisked_methods}
    for row in ledger_rows:
        key = (row.target, row.structure_method)
        if key in matrix:
            matrix[key] += row.n_generated
    return matrix


def open_obligations(matrix: dict[tuple[str, str], int]) -> list[tuple[str, str]]:
    """Dispatch priority goes to under-represented methods until the cell is filled or a
    deviation is logged. Throughput, cost and skill availability are not valid grounds
    to skip an asterisked method; a method that passed bring-up and contributed zero
    ranked backbones campaign-wide is a reportable defect."""
    return [cell for cell, n in matrix.items() if n < METHOD_FLOOR_BACKBONES]


class Dispatcher:
    """The single submit-token issuer. Exactly one, campaign-wide.

    The orchestrator hands it work lists and never loads or calls submit_gate itself.
    Any dispatch restructuring (per-target pods, screen orchestrators) must preserve
    this: two issuers means two views of the concurrency ceiling, and the race between
    them is exactly what the governor exists to prevent.
    """

    def __init__(self, app_id: str, project_tag: str) -> None:
        self.app_id = app_id
        self.project_tag = project_tag

    def dispatch(self, job) -> bool:
        if not submit_gate(self.app_id, self.project_tag, job.timeout_s,
                           gpu_type=job.gpu_type, target=job.target, stage=job.stage):
            return False
        host.compute.submit_job(job)
        return True


# ── the clock ─────────────────────────────────────────────────────────────────────────

# @block st-208 kind=protocol
CLOCK_PERIOD_MINUTES = 5
CLOCK_DISPATCH_BY_MINUTES = 15
CLOCK_LIVENESS_PATH = f"{STATE}/clock_liveness.json"


def clock_agent(campaign_end: float, write_file, now=time.time) -> None:
    """A long-lived singleton, like WATCHDOG and BUDGET: an internal loop that never
    returns between cycles.

    The premise is stated plainly in the prompt: the agent cannot tell the time and must
    not rely on its own sense of elapsed time. Dormancy (any interval neither running
    a tool call nor parked on a bounded wait) is a defect, with a target of zero
    dormant minutes across the whole window.
    """
    while now() < campaign_end:
        write_file(CLOCK_LIVENESS_PATH, {
            "set_at_utc": now(),
            "pct_elapsed": 100.0 * (1 - (campaign_end - now()) / 86400),
            "hours_remaining": (campaign_end - now()) / 3600,
        })
        time.sleep(CLOCK_PERIOD_MINUTES * 60)


def is_dormant(executing_tool_call: bool, parked_with_timeout: bool) -> bool:
    return not (executing_tool_call or parked_with_timeout)


def is_sdk_hang(has_rolling_summary_marker: bool, tool_call_in_flight: bool,
                elapsed_s: float, expected_s: float) -> bool:
    """A harness compaction restart is NOT a hang and must not trigger child
    cancellation or sandbox reaping.

    It resembles a stall (a gap with no in-flight tool call), but reaping on it would
    destroy healthy work every time the context rolls over. Only a specific call in
    flight past its expected duration counts.
    """
    if has_rolling_summary_marker and not tool_call_in_flight:
        return False
    return tool_call_in_flight and elapsed_s > expected_s


def daemon_limit(ceiling: int, live_subagents: int) -> int:
    """The orchestrator is the only process permitted to RAISE the daemon limit, and
    only to ceiling + N where N is its live sub-agent count.

    Keeping the daemon limit equal to the governor ceiling (with at most one loop
    iteration of lag) is what stops it binding a submit that submit_gate would have
    allowed. It must never exceed this bound under any rationale: phantom usage rows are
    cleared by the reap sweep, never by raising the limit.
    """
    n = min(live_subagents, SUBAGENT_HEADROOM_MAX)
    return min(DAEMON_LIMIT_MAX, max(1, ceiling + n))


# ── orchestrator discipline ───────────────────────────────────────────────────────────

# @block st-210 kind=lint
FORBIDDEN_IN_ORCHESTRATOR = (
    "time.sleep", "asyncio.sleep", "asyncio.run",
    "modal", "compute_provider", "save_artifacts",
    "modal_proto", "api_pb2", "grpclib",
)
MAX_TOOL_CALL_SECONDS = 300
MAX_CONSECUTIVE_WAITS = 5


def lint_orchestrator_source(source: str) -> list[str]:
    """These rules are checkable statically, which is the honest way to encode them.

    The orchestrator never imports modal and never touches the provider SDK: not in the
    foreground, not with a timeout, and not for diagnostics. Its only compute touchpoint
    is the host.compute job-submit/result surface.
    """
    violations = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            name = getattr(node, "module", None) or ""
            names = [a.name for a in node.names] + [name]
            violations += [f"imports {n}" for n in names
                           if any(n.startswith(f) for f in FORBIDDEN_IN_ORCHESTRATOR)]
        if isinstance(node, ast.Call):
            target = ast.unparse(node.func)
            violations += [f"calls {target}" for f in FORBIDDEN_IN_ORCHESTRATOR
                           if target.startswith(f)]
        if isinstance(node, ast.While) and _is_true_literal(node.test):
            violations.append("foreground while-True loop")
    return violations


def _is_true_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def park(next_obligation_s: float):
    """The only permitted way for the orchestrator to park.

    Timeout no longer than the gap to the next timed obligation; drain all pending
    notifications in one pass under high rate, act on the batch, then re-enter. More
    than ~5 consecutive waits with no interleaved planning, ledger, ideation or dispatch
    action is itself a defect.
    """
    return host.wait_for_notification(timeout=min(next_obligation_s, MAX_TOOL_CALL_SECONDS))


def first_action() -> dict:
    """Dispatch SETUP and BLOCK on its return. Nothing else may be dispatched until it
    returns OK with the gate module's sha256.

    SETUP alone creates the volumes, seeds the governor, and writes lib/submit_gate.py,
    providing a single origin for the artifact every dispatcher depends on.
    """
    result = host.delegate("SETUP", block=True)
    assert result["status"] == "OK", "no sub-agent may be dispatched until SETUP is OK"
    host.compute.set_concurrency_limit(150)
    return result


# ── the watchdog ──────────────────────────────────────────────────────────────────────

# @block st-214 kind=logic
HEARTBEAT_PATH = f"{STATE}/heartbeat.json"
WATCHDOG_PERIOD_MINUTES = 5
HEARTBEAT_STALE_NOTICE_MINUTES = 15
HEARTBEAT_STALE_HALT_MINUTES = 30
BUDGET_STALE_REDISPATCH_MINUTES = 20
JOBS_PER_MONITOR = 10


@dataclass
class WatchdogState:
    heartbeat_age_minutes: float
    budget_liveness_age_minutes: float
    live_gpu: int
    ceiling: int
    runaway_cycles: int


def watchdog_action(s: WatchdogState) -> list[str]:
    """The escalation ladder, and a runaway brake that runs independently of it.

    The ladder keys on heartbeat staleness: notice at 15 minutes, halt at 30. The
    runaway check keys on nothing but the live count, so it fires even when BUDGET is
    dead and the heartbeat is fresh; the two failure modes are independent and so are
    their detectors.
    Note what the halt does NOT do: it records the orchestrator's pending dispatches but
    does not issue them, because those would be fresh submitter frames during a
    ceiling=0 halt.
    """
    actions: list[str] = []
    if s.heartbeat_age_minutes > HEARTBEAT_STALE_NOTICE_MINUTES:
        actions.append("post stall notice")
        actions.append(f"write {STATE}/WAKE")
    if s.heartbeat_age_minutes > HEARTBEAT_STALE_HALT_MINUTES:
        actions.append('write ceiling=0 basis="DEAD_ORCHESTRATOR"')
        actions.append("lower daemon limit to standing singletons")
        if s.budget_liveness_age_minutes > BUDGET_STALE_REDISPATCH_MINUTES:
            actions.append("re-dispatch BUDGET")
        actions.append(f"record pending dispatches to {STATE}/pending_on_wake.json")
    if s.runaway_cycles >= 2 and s.live_gpu > max(2 * s.ceiling, s.ceiling + 50):
        actions.append('write ceiling=0 basis="WATCHDOG_RUNAWAY"')
    return actions


def watchdog_agent(campaign_end: float, app_id: str, project_tag: str,
                   write_file, now=time.time) -> None:
    """A long-lived singleton that writes its liveness file unconditionally every cycle.

    A cycle that reads state but skips the liveness write is a defect: liveness is the
    file's age, not the frame's running status, so a silent cycle is indistinguishable
    from a dead watchdog. And it never suppresses its halt on a message claiming the
    orchestrator is alive; only a fresh heartbeat file counts.
    """
    runaway_cycles = 0
    while now() < campaign_end:
        live = count_live_gpu_sandboxes(app_id, project_tag)
        write_file(f"{STATE}/watchdog_liveness.json", {"set_at_utc": now()})
        runaway_cycles += 1
        time.sleep(WATCHDOG_PERIOD_MINUTES * 60)


def budget_honors_basis(gov: Governor, heartbeat_age_minutes: float,
                        own_live_gpu: int, below_pre_halt_cycles: int) -> Governor:
    """BUDGET writes its reading fields but PRESERVES a halt it did not declare.

    Clearing another agent's halt because your own numbers look fine is exactly the
    behaviour that makes a fail-safe useless. A runaway clears only on BUDGET's own live
    count being at or below the pre-halt ceiling for two consecutive cycles.
    """
    if gov.basis == "DEAD_ORCHESTRATOR" and heartbeat_age_minutes > 15:
        gov.ceiling = 0
        return gov
    if gov.basis == "WATCHDOG_RUNAWAY":
        if below_pre_halt_cycles >= 2 and own_live_gpu <= (gov.pre_halt_ceiling or 0):
            gov.basis = "RUNAWAY_CLEARED"
            gov.ceiling = gov.pre_halt_ceiling or gov.ceiling
        else:
            gov.ceiling = 0
    return gov


def in_sandbox_preflight(governor, heartbeat, now: float) -> int:
    """The FIRST executable lines of every run_<tool>.py, before any weight download.

    This is the only control that runs when every agent frame is dead. It runs in under a
    second and prevents a halted campaign from continuing spend even if no harness
    process is alive to terminate jobs.
    """
    if governor["ceiling"] == 0 or (now - heartbeat["set_at_utc"]) > 30 * 60:
        return 0
    return -1


def monitors_needed(live_jobs: int) -> int:
    """One monitor per 10 live jobs, rebalanced so none watches fewer than 2 while
    another watches 10. A monitor with zero live jobs exits."""
    return max(0, -(-live_jobs // JOBS_PER_MONITOR))


HARVEST_SUFFIX = "mkdir -p out && cp -r <results> out/"
MIN_OUTPUT_FILE_COUNT = 2      # <= this means only stdout/stderr were harvested


def is_canary_failure(status: str, output_file_count: int) -> bool:
    """A 'success' that harvested only logs is a canary failure, not a success."""
    return status == "success" and output_file_count <= MIN_OUTPUT_FILE_COUNT


ORCHESTRATOR_TOKEN_SHARE_MAX = 1 / 3   # exceeded after hour 1 is an architecture failure


# ── autonomy ──────────────────────────────────────────────────────────────────────────

# @block st-262 kind=lint
FORBIDDEN_AT_EVERY_DEPTH = ("ask_user", "ask_about_compute")


def lint_autonomy(source: str) -> list[str]:
    """Both forbidden calls reach the human operator, not the calling agent's parent.

    That is the whole reason for the ban: at depth 3 an `ask_user` looks like asking your
    supervisor and is in fact paging a person at 4am. Coordination questions route
    through `host.send_message(kind='question')` instead. A plan may be posted for
    tracking, but not for approval.
    """
    tree = ast.parse(source)
    return [f"calls {name}" for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for name in [ast.unparse(node.func)]
            if any(name.endswith(f) for f in FORBIDDEN_AT_EVERY_DEPTH)]


def coordination_question(text: str, to: str) -> None:
    host.send_message(kind="question", text=text, to=to)
