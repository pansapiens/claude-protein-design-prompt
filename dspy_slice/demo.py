"""Run the slice end-to-end on a scripted LM, then score it with the campaign metric.

No API key and no network: `dspy.utils.DummyLM` replays a fixed script, so what is being
demonstrated is the program's control flow, the guards, and the metric -- not a model's
skill. Four cases, chosen to exercise each exit from `RosterTriage.forward`:

  1. a canary that meets all five criteria      -> DISPATCH, with no LM call at all
  2. a documented flag error                    -> RETRY, after reading paper + source
  3. UNAVAILABLE claimed after two lookups      -> BLOCKED by the st-250 guard
  4. a retry that restates a prior attempt      -> DROP, by the st-260 check

Case 3 is the interesting one. The scripted model returns a fluent, plausible, wrong
answer, and the program refuses it anyway, because the refusal is a predicate over the
logbook rather than a request to the model to be careful.

    python -m dspy_slice.demo
"""

from __future__ import annotations

import logging

import dspy
from dspy.utils.dummies import DummyLM

# DummyLM hands Refine's internal OfferFeedback predictor its JSON-encoded inputs
# verbatim, which that predictor's own type coercion then grumbles about. Real noise,
# no bearing on the slice.
logging.getLogger("dspy.predict.predict").setLevel(logging.ERROR)

from .counterexample import summary_rows
from .metric import campaign_metric, report
from .program import BringupEvidence, RosterTriage, UnguardedTriage

def protenix(**canary) -> BringupEvidence:
    """The same roster method under four different canary results."""
    return BringupEvidence(
        recipe_name="Protenix v2",
        pinned_source="https://github.com/bytedance/Protenix",
        invocation="protenix pred --input in.json --model_name protenix-v2 "
                   "--seeds 3 --cycle 10",
        roster_role="third ranking arm",
        benchmarked_p90_s=612.0,
        **canary,
    )


def case_pass() -> BringupEvidence:
    return protenix(
        container_builds=True, weights_checksum_matches=True,
        end_to_end_exit_code=0, n_designs=3, parsed_structures=3, sequences_emitted=2,
    )


def case_flag() -> BringupEvidence:
    return protenix(
        container_builds=True, weights_checksum_matches=True,
        end_to_end_exit_code=0, n_designs=3, parsed_structures=3, sequences_emitted=0,
        stderr_tail="KeyError: 'pae' -- confidence head produced no per-token PAE",
        prior_attempts=["raise --cycle from 4 to 10"],
    )


def case_unavailable() -> BringupEvidence:
    return protenix(
        container_builds=False, weights_checksum_matches=False,
        end_to_end_exit_code=1, n_designs=3, parsed_structures=0, sequences_emitted=0,
        stderr_tail="ERROR: Could not find a version that satisfies protenix==2.0.0",
        prior_attempts=["pin cuda 12.4 devel base image"],
    )


def case_restatement() -> BringupEvidence:
    return protenix(
        container_builds=True, weights_checksum_matches=True,
        end_to_end_exit_code=1, n_designs=3, parsed_structures=1, sequences_emitted=0,
        stderr_tail="CUDA error: no kernel image is available for execution",
        prior_attempts=["build image on cuda 12.4 devel base",
                        "rebuild the image against the cuda 12.4 devel base"],
    )


# ── scripted model turns ──────────────────────────────────────────────────────────────
#
# ReAct emits (next_thought, next_tool_name, next_tool_args) per iteration, then the
# extraction step emits the signature's own fields. DummyLM replays these in order.

def react(thought: str, tool: str, args: dict) -> dict:
    return {"next_thought": thought, "next_tool_name": tool, "next_tool_args": args}


FINISH = react("Enough to conclude.", "finish", {})


def script_flag() -> list[dict]:
    return [
        react("Read the method's own paper first, per the trigger rule.",
              "read_method_paper", {"method": "Protenix v2"}),
        react("Confirm the flag against the repo's release notes.",
              "search_github", {"query": "bytedance/Protenix"}),
        FINISH,
        {"reasoning": "The confidence head is off by default.",
         "cause": "CONFIG_FLAG",
         "evidence": ["corpus:10.1101/2025.01.0001",
                      "github:bytedance/Protenix"],
         "finding": "Per-token PAE requires --need_atom_confidence true, which the "
                    "canary invocation omits."},
        {"reasoning": "Untried and specific.",
         "named_difference": "pass --need_atom_confidence true",
         "concrete_change": "append --need_atom_confidence true to the pred invocation",
         "worth_trying": True},
    ]


def script_unavailable() -> list[dict]:
    """Three identical attempts, because a scripted model cannot take advice.

    `dspy.Refine` runs the module N times, scoring each with `_diagnosis_reward`, and
    between attempts it calls its own `OfferFeedback` predictor -- so the turn budget
    per round is (react x3 + extract) + feedback. The feedback turns are written out
    here rather than left to land by accident.

    The point of the case is what happens after Refine gives up: the guard in
    `forward()` still refuses the conclusion. Refine improves the odds; it is not the
    control. A real model would very likely take the advice on attempt 2 and go query
    the missing indexes, which is the good outcome -- but the campaign's guarantee
    cannot rest on "very likely".
    """
    claim = {"reasoning": "The package index has no such release.",
             "cause": "UNAVAILABLE",
             "evidence": ["pypi:protenix"],
             "finding": "protenix==2.0.0 is not published anywhere reachable."}
    attempt = [
        react("Check PyPI.", "search_pypi", {"query": "protenix"}),
        react("Check the repo.", "search_github", {"query": "bytedance/Protenix"}),
        FINISH,
        claim,
    ]
    feedback = {
        "discussion": "The diagnosis reached UNAVAILABLE after two of the five indexes "
                      "st-250 names, so the reward is 0 regardless of how right it is.",
        "advice": {"diagnose": "Before concluding UNAVAILABLE, call "
                               "search_huggingface, search_skill_catalog and "
                               "read_method_paper as well as pypi and github."},
    }
    return attempt + [feedback] + attempt + [feedback] + attempt


def script_restatement() -> list[dict]:
    return [
        react("Read the paper before blaming the build.",
              "read_method_paper", {"method": "Protenix v2"}),
        react("Check the repo for a CUDA note.",
              "search_github", {"query": "bytedance/Protenix"}),
        FINISH,
        {"reasoning": "The wheel was built for a different compute capability.",
         "cause": "ENVIRONMENT",
         "evidence": ["corpus:10.1101/2025.01.0001", "github:bytedance/Protenix"],
         "finding": "The kernel image does not match the GPU's compute capability."},
        {"reasoning": "Rebuild against the same base once more.",
         "named_difference": "rebuild the image on the cuda 12.4 devel base",
         "concrete_change": "re-run the image build",
         "worth_trying": True},
        {"reasoning": "The arm is covered by two other instruments.",
         "drop_reason": "Protenix v2 wheels do not match the fleet's compute "
                        "capability and two rebuilds have not changed that.",
         "consequence": "The campaign ships a two-arm ranking instrument; ESMFold2-Full "
                        "and the -Fast variant carry the score, and score_instrument "
                        "records ef2full_ef2fast on every row."},
    ]


# ── the same slice, unguarded ─────────────────────────────────────────────────────────
#
# Three failures that the guarded program makes unrepresentable and that the naive one
# emits without complaint. None of these are exotic: each is the model doing the
# reasonable-sounding thing rather than the thing the campaign requires.

def unguarded_dispatch() -> list[dict]:
    """Two of five criteria failed; the model calls it close enough and dispatches."""
    return [
        react("The adapter emitted nothing, but the structures parsed.",
              "search_github", {"query": "bytedance/Protenix"}),
        FINISH,
        {"reasoning": "The failure looks cosmetic and the arm is needed.",
         "action": "DISPATCH", "cause": "CONFIG_FLAG",
         "evidence": ["github:bytedance/Protenix"],
         "finding": "The adapter is probably fine at production batch size.",
         "named_difference": ""},
    ]


def unguarded_citation() -> list[dict]:
    """A DOI and a PDB id that no lookup returned, recalled from the weights."""
    return [
        react("I recall this one.", "search_pypi", {"query": "protenix"}),
        FINISH,
        {"reasoning": "The limitation is documented.",
         "action": "DROP", "cause": "KNOWN_LIMITATION",
         "evidence": ["doi:10.1038/s41586-021-03819-2", "pdb:7XYZ"],
         "finding": "The model cannot emit per-token PAE.",
         "named_difference": ""},
    ]


def unguarded_restatement() -> list[dict]:
    """A retry that rewords an attempt already made twice."""
    return [
        react("Try the image build again.", "search_github",
              {"query": "bytedance/Protenix"}),
        FINISH,
        {"reasoning": "One more rebuild should do it.",
         "action": "RETRY", "cause": "ENVIRONMENT",
         "evidence": ["github:bytedance/Protenix"],
         "finding": "The kernel image mismatches the GPU.",
         "named_difference": "rebuild the image on the cuda 12.4 devel base"},
    ]


UNGUARDED_CASES = [
    ("dispatches a method with no PASS row", case_flag, unguarded_dispatch()),
    ("cites identifiers it never fetched", case_flag, unguarded_citation()),
    ("retries a reworded prior attempt", case_restatement, unguarded_restatement()),
]

CASES = [
    ("all five criteria met", case_pass, []),
    ("documented flag error", case_flag, script_flag()),
    ("unavailable claimed early", case_unavailable, script_unavailable()),
    ("retry restates a prior attempt", case_restatement, script_restatement()),
]


def run() -> int:
    failures = 0
    print("=" * 78)
    print("SLICE: roster bring-up triage  (st-230 / st-216 / st-250 / st-260 / st-218)")
    print("=" * 78)

    for name, make_evidence, script in CASES:
        evidence = make_evidence()
        dspy.configure(lm=DummyLM(script) if script else DummyLM([{}]))
        pred = RosterTriage()(evidence=evidence)

        example = dspy.Example(evidence=evidence).with_inputs("evidence")
        checks = report(example, pred)
        score = campaign_metric(example, pred)

        print(f"\n{name}")
        print(f"  action        {pred.action}"
              + (f"   cause={pred.cause}" if hasattr(pred, "cause") else ""))
        for field in ("finding", "named_difference", "drop_reason", "consequence",
                      "rationale"):
            if getattr(pred, field, None):
                print(f"  {field:<13} {getattr(pred, field)}")
        print(f"  lookups       {[i for i, _ in pred.logbook] or 'none (no LM call)'}")
        for c in checks:
            print(f"    [{'ok ' if c.passed else 'FAIL'}] {c.block}  {c.name}"
                  f"  -- {c.detail}")
            failures += not c.passed
        print(f"  metric        {score:.2f}")

    print("\n" + "=" * 78)
    print("SAME METRIC, NO GUARDS: the obligations left in the signature docstring")
    print("=" * 78)
    print("A model that is merely told the rules, scored by the code that enforces them.")

    for name, make_evidence, script in UNGUARDED_CASES:
        evidence = make_evidence()
        dspy.configure(lm=DummyLM(script))
        pred = UnguardedTriage()(evidence=evidence)
        example = dspy.Example(evidence=evidence).with_inputs("evidence")
        checks = report(example, pred)
        print(f"\n{name}")
        print(f"  action        {pred.action}   cause={pred.cause}")
        print(f"  lookups       {[i for i, _ in pred.logbook] or 'none'}")
        for c in checks:
            print(f"    [{'ok ' if c.passed else 'FAIL'}] {c.block}  {c.name}"
                  f"  -- {c.detail}")
        print(f"  metric        {campaign_metric(example, pred):.2f}")

    print("\n" + "=" * 78)
    print("COUNTEREXAMPLE: st-137 submit_gate() as a signature")
    print("=" * 78)
    print(f"  {'job len':>8} {'dispatches':>11} {'$ of gate calls':>16} "
          f"{'wrong @0.1%':>12} {'wrong @1%':>10}")
    for row in summary_rows():
        print(f"  {row['job_minutes']:>6.0f}m {row['dispatches']:>11,} "
              f"{row['usd_of_gate_calls']:>15,.0f}  {row['wrong_at_0.1pct']:>11,.0f} "
              f"{row['wrong_at_1pct']:>10,.0f}")
    print(f"\n  Each wrong ALLOW is an ungated H100 for its full timeout: about "
          f"${summary_rows()[0]['usd_per_wrong_allow']:.2f} at 1.5 h.")
    print("  Each wrong REFUSE is silent: the campaign simply runs under pace.")
    print("  The predicate costs nothing, is exact, and fails closed on exception.")

    # Only the guarded program is asserted on. The unguarded section is supposed to
    # fail; that is what it is measuring.
    print("\n" + ("guarded program: all checks passed" if not failures
                  else f"guarded program: {failures} check(s) failed"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
