"""Signatures for one slice of the campaign: roster bring-up failure triage.

The slice is deliberately chosen to straddle the boundary this experiment is testing.
It draws on five blocks of the single-target prompt:

  st-230  Verification  -- the five roster PASS criteria, and the rule that a pod
                           without a PASS row must not dispatch the method.  MECHANICAL.
  st-216  Literature    -- on a tool that fails its validation gate, re-read that
                           method's own paper and source before declaring it broken.
  st-250  Unavailability-- query HuggingFace, GitHub, PyPI, the skill catalog and the
                           corpus before concluding a tool is unavailable; log the
                           exact queries with the conclusion.
  st-260  Perseverance  -- each retry must differ from the prior attempt in a way you
                           can name and log.
  st-218  Behavior      -- every factual claim traces to an executed computation or a
                           saved artifact you can cite; never write an external
                           identifier from memory.

Only the middle three are LM work.  st-230 is arithmetic over booleans and st-218 is a
predicate over a log, so both live in `metric.py` and in the guards in `program.py` --
never in a signature.  That division is the whole point of the exercise.
"""

from __future__ import annotations

from typing import Literal

import dspy

Cause = Literal[
    "CONFIG_FLAG",       # documented flag or default the campaign got wrong
    "KNOWN_LIMITATION",  # the method cannot do this; the paper says so
    "ENVIRONMENT",       # image, driver, CUDA, quota, transient host
    "UPSTREAM_BROKEN",   # the released artifact itself is defective
    "UNAVAILABLE",       # the tool does not exist anywhere reachable
]


class DiagnoseBringupFailure(dspy.Signature):
    """Diagnose why a roster tool failed end-to-end validation on a campaign target.

    You are triaging a bring-up failure, not fixing it yet. Before attributing the
    failure to the tool itself, consult the method's own paper and its source: a config
    flag or a documented limitation is the usual cause. Cite only artifacts you actually
    retrieved in this session; an identifier you did not fetch is not evidence.

    Conclude UNAVAILABLE only after querying every index, and say so with the queries.
    """

    recipe_name: str = dspy.InputField(desc="the roster method, e.g. 'Protenix v2'")
    pinned_source: str = dspy.InputField(desc="the upstream repo or model card URL")
    invocation: str = dspy.InputField(desc="the exact command the canary ran")
    failed_criteria: list[str] = dspy.InputField(
        desc="which of the five PASS criteria failed: builds, weights_checksum, "
             "exit_zero, structures_parse, adapter_consumes"
    )
    stderr_tail: str = dspy.InputField(desc="last lines of the failing canary")
    prior_attempts: list[str] = dspy.InputField(
        desc="named differences already tried for this method, most recent last"
    )

    cause: Cause = dspy.OutputField()
    evidence: list[str] = dspy.OutputField(
        desc="artifact references supporting the cause, one per line, each of the form "
             "'<lookup>:<identifier>' naming a lookup executed in this session"
    )
    finding: str = dspy.OutputField(desc="one sentence: what is actually wrong")


class ProposeNextAttempt(dspy.Signature):
    """Propose the next bring-up attempt for a method that failed validation.

    The attempt must differ from every prior attempt in a way you can name in a few
    words. Repeating an attempt with more hope is not a difference. If no untried
    difference is worth its compute, say so and the caller will route to a drop.
    """

    recipe_name: str = dspy.InputField()
    cause: str = dspy.InputField()
    finding: str = dspy.InputField()
    prior_attempts: list[str] = dspy.InputField()

    named_difference: str = dspy.OutputField(
        desc="a short noun phrase naming what changes, e.g. "
             "'pass --need_atom_confidence true' or 'build image on cuda 12.4 base'"
    )
    concrete_change: str = dspy.OutputField(desc="the edit to the recipe, precisely")
    worth_trying: bool = dspy.OutputField(
        desc="false when the remaining differences do not justify their compute"
    )


class TriageUnguarded(dspy.Signature):
    """The naive decomposition: one signature for the whole decision.

    This is what the slice looks like if you take the prompt's prose at face value and
    hand all of it to a model, obligations included. It is here to be measured against
    the guarded program by the same metric, not as a recommendation. Every rule in this
    docstring is a rule the guarded version enforces in Python instead.

    Decide whether to dispatch this method, retry its bring-up, or drop it. A method
    dispatches only when all five PASS criteria hold: the container builds and imports,
    the weights checksum matches upstream, one end-to-end run with 2-4 designs exits 0,
    the output parses, and the sequence-design adapter consumes one. Read the method's
    paper and source before blaming the method. Query HuggingFace, GitHub, PyPI, the
    skill catalog and the corpus before concluding it is unavailable. Any retry must
    differ from every prior attempt in a way you can name. Cite only what you fetched.
    """

    recipe_name: str = dspy.InputField()
    pinned_source: str = dspy.InputField()
    invocation: str = dspy.InputField()
    failed_criteria: list[str] = dspy.InputField()
    stderr_tail: str = dspy.InputField()
    prior_attempts: list[str] = dspy.InputField()

    action: Literal["DISPATCH", "RETRY", "DROP"] = dspy.OutputField()
    cause: Cause = dspy.OutputField()
    evidence: list[str] = dspy.OutputField()
    finding: str = dspy.OutputField()
    named_difference: str = dspy.OutputField(desc="empty unless action is RETRY")


class JustifyDrop(dspy.Signature):
    """Write the drop record for a roster method the campaign will stop trying.

    A drop is logged with its consequence stated: which arm, metric, or capability the
    campaign now lacks, and what absorbs the work. Do not soften it.
    """

    recipe_name: str = dspy.InputField()
    cause: str = dspy.InputField()
    finding: str = dspy.InputField()
    roster_role: str = dspy.InputField(
        desc="what this method was to provide, e.g. 'third ranking arm'"
    )

    drop_reason: str = dspy.OutputField(desc="one sentence, mechanically specific")
    consequence: str = dspy.OutputField(
        desc="what the campaign loses and what covers it"
    )
