# Can this prompt be decomposed into DSPy signatures and modules?

An experiment, not a conversion. One slice of the single-target prompt is rebuilt as a
[DSPy](https://github.com/stanfordnlp/dspy) program and measured, alongside a
counterexample chosen to fail.

```bash
python3 -m venv .venv && .venv/bin/pip install dspy
PYTHONPATH=. .venv/bin/python -m dspy_slice.demo
```

Runs offline on `dspy.utils.DummyLM` — no API key, no network. **No real model was
called anywhere in this experiment**, so nothing here measures a model's skill. What it
measures is the program's control flow, its guards, and whether the metric bites.

Nothing in here is part of `build.py`; the viewer does not know it exists.

---

## Verdict

**Partly feasible, useful in one direction, folly in the direction people usually reach
for DSPy.** More precisely:

DSPy's core split is signature/module (the soft part, optimizable) versus metric (the
hard part, code). All 170 blocks of the single-target prompt have now been classified by
which of those they would be, against a rubric that never mentions the existing `force`
axis, with an evidence requirement: a block counts as `metric` only if the predicate was
written down, `signature` only if the output fields were named, `scaffolding` only if the
missing DSPy capability was named. The build enforces that. 39 predicates, 11 output
specs and 26 blockers were written; `unclear` was available throughout and used once.

| Role | Blocks | Text | What it is |
|---|---:|---:|---|
| `code` | 48 | 46.0% | a computation to implement — `forward()` body or a guard |
| `metric` | 39 | 19.0% | an obligation on an artifact, decidable after the fact |
| `scaffolding` | 26 | 25.1% | campaign machinery DSPy cannot express |
| `corpus` | 32 | 3.8% | the bibliography — retrieval, not instruction |
| `inert` | 13 | 1.5% | headers and framing |
| `signature` | 11 | 4.1% | **a judgment a model must make** |
| `unclear` | 1 | 0.6% | st-264, Safety — see below |

### The prediction, and how badly it missed

Before doing this I claimed, from a 5-block sample, that ~66 of the 81 `MUST` blocks were
checkable predicates. **The real number is 28 — 35%, not 81%.** Off by a factor of 2.4,
and in the direction that flattered the thesis. Counting `metric` as a *secondary* role
too, the most generous honest reading is 45 of 81. The hand-counted "~15 judgment sites"
came out at 11, which is closer but still over.

I also assumed `MECHANICAL` mapped cleanly onto `code`. It does not: of 50 `MECHANICAL`
blocks, 33 are `code`, **9 are `metric`** (they state a property of a shipped file, not a
computation — the sheet's null policy, the companion's coverage) and **8 are
`scaffolding`** (the reap sweep, the bring-up scheduling).

### What the cross-tab actually shows

|  | code | metric | signature | scaffolding | corpus | inert | unclear |
|---|---:|---:|---:|---:|---:|---:|---:|
| `MECHANICAL` | **33** | 9 | · | 8 | · | · | · |
| `MUST` | 14 | **28** | 9 | 17 | 2 | 10 | 1 |
| `SHOULD` | · | 2 | 1 | · | **30** | · | · |
| `MAY` | 1 | · | 1 | 1 | · | 3 | · |

The two axes agree at the ends and disagree in the middle. `MECHANICAL` is two-thirds
`code`; `SHOULD` is nine-tenths `corpus`. But **`MUST` is not a DSPy category at all** —
it scatters across five roles with no majority. That is the corrected finding, and it is
sharper than the one it replaces: normative force tells you how hard a clause binds, and
that turns out to be almost independent of whether the clause is checkable. "You must" is
a statement about consequences, not about decidability.

So: you can build a DSPy program out of this document, and doing so improves it. You
cannot meaningfully *optimize* it, because the surface an optimizer acts on is nine
blocks out of 170 — the non-bibliography `SHOULD`s (epitope policy st-43, the 10%
non-all-alpha target st-69, the packaging rules st-191) plus the six `MAY`s.

### The 11 judgment sites

st-41 (multiple depositions), st-43 (epitope selection), st-112 (control selection),
st-120 (model versus design), st-196 (thread directives), st-220 (anomaly triage),
st-222 (cheapest falsifying check), st-224 (report messy results as messy), st-226 (lead
with the unfavorable reading), st-228 (standards under autonomy), st-260 (allocate by
evidence).

Ten of the eleven are epistemic rather than scientific — they govern how the campaign
reasons and reports, not what it designs. The one place the prompt asks for a genuinely
scientific judgment with a structured output is epitope and control selection.

### A limitation the classification exposed

The six roles classify *instructions*. A prompt also contains **data**, and the taxonomy
has no slot for it. The single-target dossier (st-5: UniProt P15428, C2 homodimer, NAD⁺
cofactor) came out `inert` because it carries no obligation of its own — technically
correct and clearly wrong in spirit; in DSPy it is an input field *value*. The same shows
up in the multi-target document, where the 14-row target table has no role at all. Worth
knowing before anyone reads the `inert` count as "13 blocks that do nothing".

### The one `unclear`

**st-264, Safety.** No role hosts it honestly. The bioweapons exclusion is an absolute
scope constraint with no artifact predicate, no structured output and no computation; the
stop-instruction clause is the only part with a DSPy analogue, and its force comes from
overriding every other block, which `scaffolding` does not capture. Not `inert` — it is
the strongest obligation in the document. Recorded as `unclear` rather than forced, which
is what the escape hatch was for.

---

## The slice

Roster bring-up triage: a tool fails validation, and the campaign must decide whether to
dispatch, retry, drop, or block. Chosen because it straddles the boundary rather than
sitting on one side of it. Five blocks:

| Block | Section | What it is |
|---|---|---|
| st-230 | Verification | the five roster PASS criteria; no PASS row, no dispatch. `MECHANICAL` |
| st-216 | Literature | re-read the method's paper and source before declaring it broken |
| st-250 | Unavailability | query all five indexes before concluding a tool is unavailable |
| st-260 | Perseverance | every retry differs from the prior attempt in a nameable way |
| st-218 | Behavior | every identifier cited is the literal output of a lookup you ran |

- `signatures.py` — three signatures for the judgment, plus `TriageUnguarded` (the naive
  one-signature version, kept only as a control).
- `lookups.py` — the five indexes st-250 names, as tools over a `Logbook`. The logbook
  is the mechanism: st-218 is only checkable because something recorded what was fetched.
- `program.py` — `RosterTriage`, which imports `roster_pass` and `timeout_for` from
  `pycode/` rather than restating them, and puts fail-closed guards between the model's
  conclusions and the campaign's actions.
- `metric.py` — five campaign obligations as a DSPy metric.
- `counterexample.py` — `submit_gate()` as a signature, with the arithmetic.

### What the run shows

Four cases through the guarded program, each exercising a different exit; then three
cases through the unguarded one, scored by the same metric.

```
guarded    all five criteria met              DISPATCH  1.00   (no LM call at all)
guarded    documented flag error              RETRY     1.00
guarded    unavailable claimed early          BLOCKED   1.00
guarded    retry restates a prior attempt     DROP      1.00

unguarded  dispatches a method with no PASS row         0.80   st-230 FAIL
unguarded  cites identifiers it never fetched           0.60   st-216, st-218 FAIL
unguarded  retries a reworded prior attempt             0.80   st-260 FAIL
```

The scripted model is *identically unreliable* in both columns. The difference is
entirely structural: in the guarded program those three outputs are unrepresentable.
`DISPATCH` is returned by an `if roster_pass(...)` branch the model cannot reach; a
reworded retry is caught by an edit-distance check and routed to a drop; an `UNAVAILABLE`
verdict reached after two lookups returns `BLOCKED` naming the three outstanding indexes.

`dspy.Refine` is in there too, with the campaign rule as its reward — a diagnosis the
prompt does not license scores 0 and the model gets another attempt with its own failure
in view. That is worth having, and it is not the control. A scripted model cannot take
advice, so it repeats itself three times and the guard still catches it. A real model
would probably take the advice on attempt two. "Probably" is the entire point: st-250 is
not a preference.

### The counterexample

`submit_gate()` (st-137) written as a signature, which runs and is wrong. Its body is
seven lettered comparisons between numbers read from `/state/governor.json`, wrapped so
any exception returns `False`. The prompt's own justification for that wrapper: the gate
is fail-closed "because a delayed dispatch costs seconds while an ungated H100 dispatch
costs unrecoverable dollars".

A signature cannot have that property. A predicate's failure mode is an exception, which
`except: return False` converts into a refusal. A model's failure mode is a confident,
well-formatted answer, and there is no `except` clause for that.

At the prompt's own numbers — ceiling 150, 24 hours, ~$4.39/h per H100 sandbox — the gate
is called once per container start:

```
 job len  dispatches  $ of gate calls  wrong @0.1%  wrong @1%
     5m      43,200             173           43        432
    15m      14,400              58           14        144
    45m       4,800              19            5         48
```

The dollars are the small objection. The other two columns are the real ones, plus added
latency on a path that already backs off 5–60 s under contention.

---

## Three things DSPy cannot express here

**1. The campaign itself.** DSPy programs are request/response. This document specifies a
24-hour wall clock, a $10,000 budget with a concurrency governor, >50 concurrent agents,
long-lived singleton sub-agents (WATCHDOG, BUDGET, CLOCK) with liveness files and
dead-man switches, hourly Slack cadence, and a close-out reserve. DSPy has no scheduler,
no budget, no wall clock, and no concept of an agent that must not return.

This is the `scaffolding` role: **26 blocks, 25.1% of the document by text**, each one
naming the capability DSPy lacks. The recurring blockers are wall clock, multi-agent,
scheduler, long-lived process and external side effect. Not because DSPy is deficient —
it is a different kind of object.

The classification also caught a failure mode worth naming: several blocks *look* like
metrics and are not, because the campaign never records the thing they talk about.
"Generation must stay paced with scoring" (st-160) describes a momentary queue state that
appears in no shipped artifact; "use as much time as possible while finishing on time"
(st-200) supplies no number; adversarial review of every deliverable (st-198) names no
artifact where reviews are recorded. Each reads like an obligation you could check and
isn't.

**2. Ground truth for the interesting judgments.** Optimizers need a metric that
discriminates. `campaign_metric` scores *compliance*, which is exactly what the prompt
specifies and says nothing about whether the epitope was well chosen. The signal for
that arrives from a CRO weeks later, on 30 designs. There is no trainset, and 30
end-of-campaign labels will not bootstrap one.

**3. Anything worth rewriting.** MIPROv2 and GEPA search over instructions and
demonstrations. Here the instructions are thresholds, enum values, file paths, column
names and lettered procedures whose wording is load-bearing. An optimizer that improved
the phrasing of st-137 would have broken it.

I did not run MIPROv2 or GEPA — with nine optimizable blocks and no trainset there was
nothing to run them on. That is the finding, not an omission.

---

## What I would actually take from this

Not "port the campaign to DSPy". Two narrower things:

**The metric is the prompt — for 39 blocks, not for most of it.** `metric.py` is the
transferable idea and it does not need DSPy: written as checks that run on every output,
those obligations stop depending on an agent's recall across a 24-hour window. But the
measurement cut this claim down. It is 39 blocks primarily and 74 counting secondary
roles, not the majority of the document, and the reason is instructive: the blocks that
resist are the ones whose subject the campaign never writes down. Making them checkable
is a change to what the campaign *records*, not to how the prompt is worded.

**Typed outputs at the judgment sites.** The 11 places that need a verdict currently get
one in free text, and the obligations on it (cite what you fetched; name the difference;
state the consequence) are enforced by review. As output fields they are enforced by
parsing, and st-218's provenance rule becomes checkable rather than aspirational — but
only if a logbook is recording lookups, which is again a change to the program, not to
the prompt.

Both are available without adopting DSPy. What DSPy contributes is the discipline of
being made to write the metric down.
