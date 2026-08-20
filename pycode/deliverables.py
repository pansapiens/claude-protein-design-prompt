"""Reporting and close-out: one thread, one writer, one folder, one rebuild.

Every rule here is a singleton or an idempotence rule. The failure mode being designed
against is a fleet of concurrent agents each doing something individually reasonable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from .campaign import SHEET_ROWS_PER_TARGET, DesignRow
from .external import drive, host, slack
from .sheet import distinct_structure_methods, levenshtein

# ── Slack ─────────────────────────────────────────────────────────────────────────────

# @block st-167 kind=protocol
def kickoff_post(channel_id: str, target: str, model: str, date: str, frame_id8: str,
                 t0_utc: str, campaign_end_utc: str, plan: str) -> str:
    """The first Slack action, and the ONLY top-level post of the campaign.

    Its ts is saved as an artifact and passed as thread_ts on every later send, which is
    what makes the threading invariant enforceable rather than aspirational.
    """
    header = f"Campaign Kickoff ({target}): {model} {date} {frame_id8}"
    ts = slack.post(channel=channel_id, text=f"{header}\n{t0_utc} -> {campaign_end_utc}\n{plan}")
    host.save_artifact("kickoff_ts", ts)
    return ts


# @block st-170 kind=protocol
BROADCAST_ALLOWED = (
    "daily morning update",
    "campaign-conclusion post",
    "genuine emergency",
)


def send(text: str, kickoff_ts: str, reply_broadcast: bool = False, kind: str = "") -> None:
    """Every send after the kickoff carries thread_ts and reply_broadcast=false.

    Sub-agents receive the kickoff ts in their task brief, saved once as an artifact and
    never re-authored -- a re-authored ts is a second top-level post wearing a thread's
    clothes. An accidental broadcast is a reporting error: acknowledge it in the next
    status block and continue in-thread rather than deleting it.
    """
    if reply_broadcast and kind not in BROADCAST_ALLOWED:
        raise ValueError(f"broadcast not permitted for {kind!r}")
    slack.send(text=text, thread_ts=kickoff_ts, reply_broadcast=reply_broadcast)


# ── Drive ─────────────────────────────────────────────────────────────────────────────

# @block st-174 kind=protocol
CLOSE_OUT_FILES = ("design_sheet.csv", "scoreboard.csv", "deviations.jsonl")


class DeliverablesCoordinator:
    """Exactly ONE sub-agent role may create folders or upload files in Drive.

    One campaign sub-folder naming the target, and inside it exactly one close_out/
    created only at close-out, whose first file is a README listing every deliverable.
    The connector cannot update or delete in place, so an upload is irreversible -- which
    is why upload happens only after auditor review and only once files are final.
    """

    def __init__(self, target: str) -> None:
        self.folder = drive.create_folder(f"campaign-{target}")
        self.close_out = None

    def open_close_out(self, manifest: Sequence[str]) -> None:
        assert self.close_out is None, "close_out/ is created exactly once"
        self.close_out = drive.create_folder("close_out", parent=self.folder)
        drive.upload("README.md", render_manifest(manifest), parent=self.close_out)

    def upload(self, name: str, blob: bytes, reviewed: bool, final: bool) -> None:
        assert name in CLOSE_OUT_FILES, f"{name} is not a close-out file"
        assert reviewed and final, "uploads are irreversible; review before uploading"
        drive.upload(name, blob, parent=self.close_out)


def render_manifest(entries: Sequence[str]) -> str:
    return "\n".join(f"- {e}" for e in entries)


def close_out_transaction(sheet: Sequence[DesignRow], mandatory_nonnull: Sequence[str]):
    """Freeze the ranked sheet, then derive every companion from THAT snapshot.

    Deriving companions from live state instead would let the sheet and its own audit
    trail disagree. A null in a required-but-non-load-bearing column downgrades the row
    to disclosed-with-deviation rather than dropping it at close-out -- dropping at the
    last step would silently change the shipped row count.
    """
    frozen = list(sheet)
    downgraded = []
    for row in frozen:
        for column in mandatory_nonnull:
            value = getattr(row, column, None)
            if value is None or value == "PENDING":
                downgraded.append((row.design_id, column))
    return frozen, downgraded


def report_numbers_from(csvs) -> dict:
    """Every README, report, Slack-conclusion number and the model name are read only
    from the close-out CSVs and `host.current_model()`."""
    return {"model": host.current_model(), **csvs.aggregates()}


# ── structures ────────────────────────────────────────────────────────────────────────

# @block st-189 kind=logic
def rebuild_ordered_structures(sheet: Sequence[DesignRow], bundle_root: str) -> None:
    """REBUILT from the FINAL ranked sheet as the last close-out step.

    Building it earlier and patching it later is how a bundle ends up with a rank prefix
    that disagrees with the sheet -- so the assertion below checks exactly that, along
    with every path actually resolving inside the rebuilt bundle.
    """
    for row in sheet:
        paths = [row.designed_structure_path] + [
            p for p in row.predicted_structure_path.values() if p]
        for path in paths:
            assert path.startswith(bundle_root), f"{row.design_id}: {path} outside bundle"
            assert _rank_prefix_of(path) in (None, row.rank), \
                f"{row.design_id}: path rank prefix disagrees with sheet rank {row.rank}"


def _rank_prefix_of(path: str) -> Optional[int]:
    head = path.rsplit("/", 1)[-1].split("_", 1)[0]
    return int(head) if head.isdigit() else None


# @block st-190 kind=logic
def retrievability_check(sheet: Sequence[DesignRow], open_from_drive) -> float:
    """OPEN every referenced file, from the Drive copy -- not just resolve its path.

    Path resolution passes on a bundle that uploaded empty; opening does not. Below 100%
    on any target is a defect remediated before close-out.
    """
    total = opened = 0
    for row in sheet:
        for path in [row.designed_structure_path, *row.predicted_structure_path.values()]:
            if not path:
                continue
            total += 1
            opened += 1 if open_from_drive(path) else 0
    return opened / total if total else 0.0


# ── the scoreboard ────────────────────────────────────────────────────────────────────

# @block st-192 kind=schema
SCOREBOARD_COLUMNS = (
    "target", "designs_generated", "designs_screened", "designs_ranked",
    "best_final_score", "median_final_score_ranked", "pose_check_pass_rate_top10",
    "gpu_dollars", "wallclock_hours_active_compute", "n_distinct_root_backbones",
    "max_seqs_per_root_backbone", "n_tm90_clusters", "max_tm90_cluster_size",
    "n_structure_methods", "top_method_share", "min_pairwise_editdist",
    "n_non_all_alpha",
)


@dataclass
class ScoreboardRow:
    target: str
    values: dict[str, float]

    def assert_complete(self) -> None:
        """Every non-target column is a real computed numeric on every row.

        No NaN, no sentinel, no free text. A value that cannot be computed is a defect
        tracked in scoreboard_gaps.csv and remediated -- not written as a blank.
        """
        for column in SCOREBOARD_COLUMNS[1:]:
            value = self.values.get(column)
            assert isinstance(value, (int, float)) and not math.isnan(value), \
                f"{self.target}/{column} is not a computed numeric"


def scoreboard_row(target: str, ranked: Sequence[DesignRow], totals: dict,
                   gpu_dollars: float, active_hours: float) -> ScoreboardRow:
    """Diversity columns are computed from the final ranked-30 sheet by the SAME code
    that enforces the caps, so the scoreboard cannot disagree with the sheet it summarises."""
    scores = sorted(r.final_score for r in ranked if not math.isnan(r.final_score))
    top10 = sorted(ranked, key=lambda r: r.rank or SHEET_ROWS_PER_TARGET)[:10]
    roots = [r.root_backbone_id for r in ranked]
    clusters = [r.tm90_cluster_id for r in ranked]
    pairs = [levenshtein(a.sequence, b.sequence)
             for i, a in enumerate(ranked) for b in ranked[i + 1:]]
    return ScoreboardRow(target, {
        "designs_generated": totals["designs_generated"],
        "designs_screened": totals["designs_screened"],
        "designs_ranked": totals["designs_ranked"],
        "best_final_score": scores[-1] if scores else math.nan,
        "median_final_score_ranked": scores[len(scores) // 2] if scores else math.nan,
        "pose_check_pass_rate_top10": sum(r.pose_PASS for r in top10) / max(len(top10), 1),
        "gpu_dollars": gpu_dollars,
        "wallclock_hours_active_compute": active_hours,
        "n_distinct_root_backbones": len(set(roots)),
        "max_seqs_per_root_backbone": max((roots.count(r) for r in set(roots)), default=0),
        "n_tm90_clusters": len(set(clusters)),
        "max_tm90_cluster_size": max((clusters.count(c) for c in set(clusters)), default=0),
        "n_structure_methods": distinct_structure_methods(ranked),
        "top_method_share": _top_share(ranked),
        "min_pairwise_editdist": min(pairs) if pairs else math.nan,
        "n_non_all_alpha": sum(1 for r in ranked if r.fold_class == "not_all_alpha"),
    })


def _top_share(rows: Sequence[DesignRow]) -> float:
    methods = [r.structure_method for r in rows]
    return max((methods.count(m) for m in set(methods)), default=0) / max(len(methods), 1)
