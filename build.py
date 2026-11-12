#!/usr/bin/env python3
"""Generate index.html: a two-pane annotated viewer for the protein-binder-design prompts.

Reads the frozen release bundle plus annotations/*.json and emits one self-contained HTML
file. Stdlib only. See CLAUDE.md for the segmentation contract and annotation schema.
"""

from __future__ import annotations

import ast
import difflib
import html
import io
import json
import keyword
import re
import subprocess
import sys
import token as tokmod
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "protein_binder_design_prompts_release"
PROMPTS = BUNDLE / "prompts"
SINGLE = PROMPTS / "single_target" / "15-PGDH.md"
MULTI = PROMPTS / "multi_target_binder_design_prompt.md"
SINGLE_DIR = PROMPTS / "single_target"
ANNOTATIONS = ROOT / "annotations"
PYCODE = ROOT / "pycode"
OUT = ROOT / "index.html"

EXPECT = {"st": 170, "mt": 184, "sections": 32}

FORCES = ("MECHANICAL", "MUST", "SHOULD", "MAY")
OWNERS = (
    "orchestrator", "SETUP", "BUDGET", "WATCHDOG", "CLOCK", "SCRIBE", "DISPATCH",
    "DELIVERABLES", "monitor", "sheet-writer", "any-agent",
)
TAGS = (
    "framing", "objective", "target-biology", "reference", "corpus", "tooling", "installation",
    "licensing", "design-method", "sequence-design", "filtering", "scoring", "metric",
    "calibration", "gate", "diversity-cap", "provenance", "data-retention", "compute", "budget",
    "concurrency", "orchestration", "delegation", "cadence", "reporting", "deliverable",
    "verification", "epistemics", "failure-handling", "isolation", "safety",
)


# --------------------------------------------------------------------------------------
# segmentation
# --------------------------------------------------------------------------------------

SECTION_RE = re.compile(r"^([A-Z][A-Za-z ,*/\-]{2,45}):")
LIST_MARKER_RE = re.compile(r"^(\s*)((?:\d+\.|[-*])\s+)")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def depth_of(line: str) -> int:
    indent = len(line) - len(line.lstrip(" "))
    # observed indents: 0, 3, 4, 7 -> depths 0, 1, 2, 3
    return {0: 0, 3: 1, 4: 2, 7: 3}.get(indent, min(3, indent // 3))


def read_blocks(path: Path, prefix: str) -> tuple[list[dict], list[dict]]:
    """Split a prompt into blocks (one per non-blank line) and labelled sections."""
    blocks: list[dict] = []
    sections: list[dict] = []
    current = {"id": "preamble", "title": "Preamble", "index": 0}

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        m = SECTION_RE.match(raw)
        if m:
            title = m.group(1).strip()
            current = {"id": slugify(title), "title": title, "index": len(sections) + 1}
            sections.append(dict(current, line=lineno))
        blocks.append({
            "id": f"{prefix}-{lineno}",
            "line": lineno,
            "depth": depth_of(raw),
            "section": current["id"],
            "raw": raw.strip(),
        })
    return blocks, sections


# --------------------------------------------------------------------------------------
# inline entity tokenisation
# --------------------------------------------------------------------------------------

TOOLS = [
    "AlphaFold-Multimer-v3", "AlphaFold-Multimer", "AlphaFold3", "AlphaFold2", "AlphaProteo",
    "Proteina-Complexa", "Protpardelle-1c", "FreeBindCraft", "BindCraft", "RFdiffusion3",
    "RFdiffusion", "BoltzDesign1", "HalluDesign", "Protein Hunter", "ProteinHunter", "BoltzGen",
    "PXDesign", "FoldCraft", "Genie3", "Mosaic", "Protenix v2", "Protenix", "Chai-1", "Boltz-2",
    "Boltz-1", "SolubleMPNN", "ProteinMPNN", "SolubleCaliby", "Caliby", "ESMFold2-Full",
    "ESMFold2-Fast", "ESMFold2", "ESMFold", "OpenFold3", "OpenFold", "ColabFold", "AF_Unmasked",
    "MMseqs2", "UniRef90", "PyRosetta", "Rosetta", "ESM3", "ESMC", "DockQ", "ipsae.py", "ipSAE",
    "DSSP", "Modal", "Slack", "Google Drive", "Twist Bioscience", "Adaptyv Bio", "ProteinBase",
    "HuggingFace", "GitHub", "PyPI", "Zenodo", "OF3", "AF3", "Claude Science",
]

METRICS = [
    "ipSAE_min", "sc_DockQ", "pose_dockq", "pose_PASS", "rank_zscore", "final_score", "lcp_score",
    "iptm_binder", "ipTM", "LIS", "pLDDT", "TM-score", "CA-RMSD", "RMSD", "Levenshtein",
    "selectivity_delta", "z-score", "log-likelihood", "pseudo-perplexity",
    "Local Composition Perplexity", "LCP",
]

BIOLOGY = [
    "15-PGDH", "HPGD", "GDF-8", "GDF-11", "TREM2", "EGFR", "PD-L1", "IL-7Ra", "IL-7Rα", "TNFa",
    "TNFα", "VEGF-A", "TrkA", "RBX1", "BHRF1", "BBF-14", "Nipah-G", "Cas9", "SpCas9", "MBP",
    "Myostatin", "Barnase", "Barstar", "Ubiquitin", "NAD⁺", "sgRNA",
]

LITERALS = [
    "CONSTRUCT_FAIL", "REDUCED_MASK", "GATE_ERROR", "STALE_OR_MISSING_GOVERNOR",
    "LONG_TIMEOUT_OVER_PACE", "BILLING_DARK_WARN", "BILLING_DARK", "DEAD_ORCHESTRATOR",
    "WATCHDOG_RUNAWAY", "ORCHESTRATOR_RESUMED", "UNCALIBRATED", "CALIBRATED", "BOOTSTRAP",
    "HARVEST", "REJECT", "PASS", "NaN",
]

ROLES = ["SETUP", "BUDGET", "WATCHDOG", "CLOCK", "SCRIBE", "DISPATCH", "DELIVERABLES"]
STAGES = ["TOOL-BRINGUP", "INTERMEDIATE", "SCREEN", "FINAL"]


def _alt(words: list[str]) -> str:
    """Alternation of literal words, longest first so prefixes don't win."""
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


CORPUS_DIRS = [
    "01 Web Pages", "02 ProteinBase", "03 Papers + Supplementary", "04 Linked Data",
    "05 Oversized Files", "06 Prompt Figures", "07 Prompt-Cited Papers",
]

TOKEN_RE = re.compile(
    r"(?P<code>`[^`]+`)"
    r"|(?P<citation>\[[^\]]+\]\([^)]+\))"
    # Markdown emphasis only: the delimiter must hug its content and stay short, so
    # arithmetic ("2 * governor.ceiling") and the roster's footnote asterisks
    # ("RFdiffusion*") are not mistaken for a pair.
    r"|(?P<emph>(?<![\w*])\*\*(?=\S)[^*\n]{1,40}(?<=\S)\*\*(?![\w*])"
    r"|(?<![\w*])\*(?=\S)[^*\n]{1,40}(?<=\S)\*(?![\w*]))"
    r"|(?P<placeholder><[A-Za-z][A-Za-z0-9 _-]{1,40}>)"
    rf"|(?P<corpus>\"(?:{_alt(CORPUS_DIRS)})\")"
    r"|(?P<artifact>/(?:state|ledger)/[A-Za-z0-9_./{}-]+"
    r"|\b[A-Za-z0-9_]+\.(?:py|json|csv|parquet|jsonl|md|txt|pdf|sha256|a3m|cif|pdb|tar|zip|xlsx)"
    r"(?:\.gz)?\b)"
    r"|(?P<flag>--[a-z][a-z0-9_]*)"
    r"|(?P<call>\b[a-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]{2,})+(?:\(\))?)"
    rf"|(?P<tool>\b(?:{_alt(TOOLS)})\b)"
    rf"|(?P<metric>\b(?:{_alt(METRICS)})\b)"
    rf"|(?P<biology>(?:{_alt(BIOLOGY)}))"
    rf"|(?P<role>\b(?:{_alt(ROLES)})\b)"
    rf"|(?P<stage>\b(?:{_alt(STAGES)})\b)"
    rf"|(?P<literal>\b(?:{_alt(LITERALS)})\b|\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b)"
    r"|(?P<accession>\b[A-NR-Z][0-9][A-Z0-9]{3}[0-9]\b|\bO[0-9][A-Z0-9]{3}[0-9]\b)"
    r"|(?P<ident>\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b|\b[a-z_][a-z0-9_]{2,}\(\))"
    # Numbers: currency, percent, grouped, scientific, unit-bearing, decimal, and bare
    # integers -- but only where not glued to a word by a hyphen or slash ("15-PGDH",
    # "07 Prompt-Cited Papers" and the like are not constants), and never leading-zero.
    r"|(?P<constant>\$[\d,]+(?:\.\d+)?"
    r"|\b\d+(?:\.\d+)?\s?(?:%|pp)(?![\w-])"
    r"|\b\d{1,3}(?:,\d{3})+\b"
    r"|\b\d+(?:\.\d+)?e-?\d+\b"
    r"|\b\d+(?:\.\d+)?\s?(?:hours?|minutes?|seconds?|GiB|H100)(?![\w-])"
    r"|(?<![\w.-])\d+\.\d+(?![\w.-])"
    r"|(?<![\w.$/-])(?!0\d)\d{2,}(?![\w.%/-]))"
)

# Fine-grained class -> visual group used by the stylesheet.
GROUP = {
    "code": "code", "citation": "cite", "emph": "emph", "placeholder": "slot",
    "corpus": "cite", "artifact": "code", "flag": "code", "call": "code", "ident": "code",
    "tool": "tool", "metric": "metric", "biology": "bio", "accession": "bio",
    "role": "ctrl", "stage": "ctrl", "literal": "ctrl", "constant": "num",
}


def tokenise(text: str, counter: dict[str, int]) -> str:
    """Render one block's raw text to HTML with entity spans. Escapes as it emits."""
    marker = ""
    m = LIST_MARKER_RE.match(text)
    if m:
        marker = f'<span class="marker">{html.escape(m.group(2).strip())}</span> '
        text = text[m.end():]

    out: list[str] = []
    pos = 0
    for match in TOKEN_RE.finditer(text):
        kind = match.lastgroup
        assert kind is not None
        out.append(html.escape(text[pos:match.start()]))
        frag = match.group()
        counter[kind] = counter.get(kind, 0) + 1

        if kind == "citation":
            cite = re.match(r"\[([^\]]+)\]\(([^)]+)\)", frag)
            assert cite is not None
            label, href = cite.groups()
            out.append(
                f'<a class="ent ent-cite" href="{html.escape(href, quote=True)}" '
                f'target="_blank" rel="noopener" data-href="{html.escape(href, quote=True)}"'
                f'>{html.escape(label)}</a>'
            )
        elif kind == "emph":
            # Keep the markdown asterisks (fidelity) but fade them and italicise the span.
            n = 2 if frag.startswith("**") else 1
            body, star = html.escape(frag[n:-n]), "*" * n
            out.append(f'<em class="ent ent-emph" data-k="emph"><span class="ast">{star}</span>'
                       f'{body}<span class="ast">{star}</span></em>')
        else:
            out.append(
                f'<span class="ent ent-{GROUP[kind]}" data-k="{kind}">{html.escape(frag)}</span>'
            )
        pos = match.end()
    out.append(html.escape(text[pos:]))
    return marker + "".join(out)


ANCHOR_RE = re.compile(r'<a [^>]*data-href="([^"]*)"[^>]*>(.*?)</a>')


def plain_text(rendered: str) -> str:
    """Inverse of tokenise, for the round-trip fidelity assertion."""
    restored = ANCHOR_RE.sub(lambda m: f"[{m.group(2)}]({m.group(1)})", rendered)
    return html.unescape(re.sub(r"<[^>]+>", "", restored))


# --------------------------------------------------------------------------------------
# cross-document analysis
# --------------------------------------------------------------------------------------

SLOT_RULES = (
    ("TASK_TARGET", lambda t: t.startswith("Task:"),
     "Target name and synonyms; the GDF-8 prompts add a counter-target and a third goal."),
    ("TARGET_DOSSIER", lambda t: t.startswith(("Human ", "Nipah", "*S.", "*E.", "The ", "BBF-14",
                                               "Epstein", "EBV")),
     "UniProt accession, oligomeric state, cofactors, assay construct, competition link."),
    ("COMPETITION_REFS", lambda t: re.match(r"^\d+\. \[", t) is not None,
     "0-4 target-specific competition references are prepended, renumbering the shared list."),
    ("CONSTRUCT_CLAUSE", lambda t: t.startswith("For the target(s) of interest"),
     "Cas9 only: widened from 'scoring construct' to 'design and scoring constructs' "
     "because the functional unit is a 1:1 RNP."),
    ("OLIGOMER_CLAUSE", lambda t: t.startswith("7. For oligomeric targets"),
     "Parenthetical naming the target's oligomeric state, or dropped for monomers."),
    ("SELECTIVITY_CLAUSES", lambda t: True,
     "Present only on the two GDF-8 prompts: counter-target arm at the validation gate, "
     "selectivity-directed optimization, and selectivity terms in the ranking formula."),
)


def classify_slot(text: str) -> tuple[str, str]:
    for name, test, why in SLOT_RULES:
        if test(text):
            return name, why
    return "OTHER", ""


def derive_slots() -> tuple[list[dict], list[dict]]:
    """Diff all 16 single-target prompts against the canonical one to find the variable slots.

    Returns (varying lines, slots grouped semantically). Nothing here is hardcoded from a
    previous run: if a 17th prompt appears with a new slot it shows up as its own group.
    """
    canon = [l.strip() for l in SINGLE.read_text(encoding="utf-8").splitlines() if l.strip()]
    varying: dict[int, set[str]] = {}
    for path in sorted(SINGLE_DIR.glob("*.md")):
        if path == SINGLE:
            continue
        lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        sm = difflib.SequenceMatcher(None, canon, lines, autojunk=False)
        for tag, i1, i2, _j1, _j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            for i in range(i1, max(i2, i1 + 1)):
                if i < len(canon):
                    varying.setdefault(i, set()).add(path.stem)

    lines_out, groups = [], {}
    for i, targets in sorted(varying.items()):
        name, why = classify_slot(canon[i])
        lines_out.append({"index": i, "text": canon[i], "targets": sorted(targets), "slot": name})
        g = groups.setdefault(name, {"slot": name, "why": why, "lines": [], "targets": set()})
        g["lines"].append(i)
        g["targets"].update(targets)

    order = [r[0] for r in SLOT_RULES] + ["OTHER"]
    slots = sorted(groups.values(), key=lambda g: order.index(g["slot"]))
    for g in slots:
        g["targets"] = sorted(g["targets"])
        g["n_lines"] = len(g["lines"])
    return lines_out, slots


def align_documents(st: list[dict], mt: list[dict]) -> list[dict]:
    """Line-level alignment of single vs multi, with word-level opcodes inside changed pairs."""
    a = [b["raw"] for b in st]
    b = [x["raw"] for x in mt]
    regions: list[dict] = []
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        pairs = []
        if i2 - i1 == j2 - j1:
            for k in range(i2 - i1):
                pairs.append(word_diff(a[i1 + k], b[j1 + k]))
        regions.append({
            "kind": "table" if (i2 - i1) != (j2 - j1) else "scaled",
            "section": st[i1]["section"] if i1 < len(st) else "",
            "st_ids": [st[i]["id"] for i in range(i1, i2)],
            "mt_ids": [mt[j]["id"] for j in range(j1, j2)],
            "pairs": pairs,
        })
    return regions


def word_diff(left: str, right: str) -> dict:
    la, lb = left.split(" "), right.split(" ")
    sm = difflib.SequenceMatcher(None, la, lb, autojunk=False)
    out_a, out_b = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        out_a.append({"t": tag, "s": " ".join(la[i1:i2])})
        out_b.append({"t": tag, "s": " ".join(lb[j1:j2])})
    return {"a": [c for c in out_a if c["s"]], "b": [c for c in out_b if c["s"]]}


# --------------------------------------------------------------------------------------
# pycode: the MECHANICAL clauses re-coded as one importable package
# --------------------------------------------------------------------------------------

BLOCK_MARKER_RE = re.compile(r"^#\s*@block\s+(?P<rest>.+?)\s*$")
KINDS = ("logic", "schema", "config", "protocol", "lint")

# Files in reading order; the viewer shows regions in this order too.
PYCODE_FILES = (
    "campaign.py", "roster.py", "gates.py", "scoring.py", "governor.py",
    "ledger.py", "sheet.py", "deliverables.py", "orchestration.py",
)

# Highlight classes. Deliberately few: this is read at annotation-card size, and a
# fifteen-colour theme at 12px is noise, not information.
PY_CLASS = {
    tokmod.COMMENT: "c-com", tokmod.STRING: "c-str", tokmod.NUMBER: "c-num",
    tokmod.OP: "c-op",
}
PY_BUILTINS = frozenset(dir(__builtins__) if isinstance(__builtins__, dict)
                        else dir(__builtins__)) | {"self"}


def highlight(source: str) -> str:
    """Syntax-highlight Python with the stdlib tokenizer, preserving every byte.

    Gaps between tokens are emitted verbatim, so the rendered text round-trips to the
    source exactly -- the same guarantee the prompt panes carry.
    """
    out: list[str] = []
    row, col = 1, 0
    lines = source.splitlines(keepends=True)
    prev_name = ""
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return html.escape(source)

    for tok in toks:
        (srow, scol), (erow, ecol) = tok.start, tok.end
        # verbatim gap between the previous token and this one
        while (row, col) < (srow, scol):
            line = lines[row - 1] if row - 1 < len(lines) else ""
            if row < srow:
                out.append(html.escape(line[col:]))
                row, col = row + 1, 0
            else:
                out.append(html.escape(line[col:scol]))
                col = scol
        cls = PY_CLASS.get(tok.type)
        if tok.type == tokmod.NAME:
            if keyword.iskeyword(tok.string):
                cls = "c-kw"
            elif prev_name in ("def", "class"):
                cls = "c-def"
            elif tok.string in PY_BUILTINS:
                cls = "c-bi"
            prev_name = tok.string
        elif tok.type not in (tokmod.NL, tokmod.NEWLINE, tokmod.INDENT, tokmod.DEDENT):
            prev_name = ""
        text = html.escape(tok.string)
        out.append(f'<span class="{cls}">{text}</span>' if cls else text)
        row, col = erow, ecol
    return "".join(out)


def _region_bounds(path: Path) -> list[dict]:
    """Split one module into `# @block` regions. A region runs to the next marker."""
    lines = path.read_text(encoding="utf-8").splitlines()
    marks = []
    for i, line in enumerate(lines, start=1):
        m = BLOCK_MARKER_RE.match(line)
        if not m:
            continue
        parts = m.group("rest").split()
        ids = [p for p in parts if p.startswith(("st-", "mt-"))]
        kinds = [p.split("=", 1)[1] for p in parts if p.startswith("kind=")]
        assert ids, f"{path.name}:{i}: @block marker names no block id"
        assert len(kinds) == 1 and kinds[0] in KINDS, \
            f"{path.name}:{i}: @block needs one kind= from {KINDS}"
        marks.append({"line": i, "ids": ids, "kind": kinds[0]})

    regions = []
    for n, mark in enumerate(marks):
        end = marks[n + 1]["line"] - 1 if n + 1 < len(marks) else len(lines)
        body = lines[mark["line"]: end]
        while body and not body[-1].strip():
            body.pop()
        regions.append(dict(mark, file=path.name, source="\n".join(body) + "\n"))
    return regions


def _names(path: Path, regions: list[dict]) -> None:
    """Attach the names each region defines and the names it borrows from elsewhere."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
    for region in regions:
        region["defines"], region["_uses"] = [], set()
    for node in tree.body:
        home = None
        for region in regions:
            if node.lineno > region["line"]:
                home = region
        if home is None:
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            home["defines"].append(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            home["defines"] += [t.id for t in targets if isinstance(t, ast.Name)]
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                home["_uses"].add(sub.id)


def load_pycode(known_ids: set[str], mechanical: set[str]) -> tuple[dict, dict]:
    """Read pycode/, verify it, and key the regions by the prompt block they encode."""
    regions: list[dict] = []
    for name in PYCODE_FILES:
        path = PYCODE / name
        assert path.exists(), f"pycode/{name} is missing"
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
        found = _region_bounds(path)
        _names(path, found)
        regions += found

    # Every name, and the region that defines it -- this is what makes the shared
    # vocabulary visible: a card can say "calls submit_gate(), defined at st-137".
    defined_by: dict[str, str] = {}
    for region in regions:
        for name in region["defines"]:
            defined_by.setdefault(name, region["ids"][0])

    by_block: dict[str, dict] = {}
    for region in regions:
        for bid in region["ids"]:
            assert bid in known_ids, f"@block {bid} is not a block in either prompt"
            entry = by_block.setdefault(bid, {"regions": [], "defines": [], "uses": []})
            rendered = highlight(region["source"])
            assert plain_text(rendered) == region["source"], \
                f"highlighter altered {region['file']}:{region['line']}"
            entry["regions"].append({
                "file": region["file"], "line": region["line"] + 1,
                "kind": region["kind"], "html": rendered,
            })
            entry["defines"] += region["defines"]
            for name in sorted(region["_uses"]):
                owner = defined_by.get(name)
                if owner and owner != bid and not any(u["name"] == name
                                                      for u in entry["uses"]):
                    entry["uses"].append({"name": name, "block": owner})

    uncovered = sorted(mechanical - set(by_block), key=lambda b: int(b.split("-")[1]))
    assert not uncovered, f"MECHANICAL block(s) with no pycode region: {uncovered}"

    proc = subprocess.run([sys.executable, "-m", "pycode.selftest"], cwd=ROOT,
                          capture_output=True, text=True)
    assert proc.returncode == 0, f"pycode selftest failed:\n{proc.stdout}{proc.stderr}"

    meta = {
        "files": list(PYCODE_FILES),
        "n_regions": len(regions),
        "n_blocks": len(by_block),
        "selftest": proc.stdout.strip(),
        "kinds": {k: sum(1 for r in regions if r["kind"] == k) for k in KINDS},
    }
    return by_block, meta


def alias_pycode(by_block: dict, mt_notes: dict, regions: list[dict]) -> None:
    """Give multi-target blocks the single-target code they correspond to.

    Byte-identical blocks alias outright. Blocks inside a changed region alias with a
    flag, because the code is the same and only the constants moved -- which is the
    finding the delta view already makes.
    """
    for mid, note in mt_notes.items():
        src = note.get("inherited")
        if src in by_block:
            by_block[mid] = {"alias": src}
    for region in regions:
        if len(region["st_ids"]) != len(region["mt_ids"]):
            continue
        for st_id, mt_id in zip(region["st_ids"], region["mt_ids"]):
            if st_id in by_block and mt_id not in by_block:
                by_block[mt_id] = {"alias": st_id, "rescaled": True}


# --------------------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------------------

def load_annotations(name: str) -> dict:
    path = ANNOTATIONS / f"{name}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def inherit_annotations(st_blocks: list[dict], st_notes: dict,
                        mt_blocks: list[dict], mt_notes: dict) -> dict:
    """Multi-target blocks that are byte-identical to a single-target block reuse its note.

    Only the 16 changed regions need hand-authored multi-target annotations; everything
    else is the same document. `inherited` is flagged so the viewer can say so.
    """
    by_text = {b["raw"]: b["id"] for b in st_blocks}
    merged = {}
    for blk in mt_blocks:
        if blk["id"] in mt_notes:
            merged[blk["id"]] = dict(mt_notes[blk["id"]])
        else:
            src = by_text.get(blk["raw"])
            if src and src in st_notes:
                # Reference, not a copy: the viewer resolves it, and the editable
                # annotation block stays readable instead of repeating 142 paragraphs.
                merged[blk["id"]] = {"inherited": src}
    return merged


def validate(blocks: list[dict], notes: dict, label: str, strict: bool) -> list[str]:
    problems = []
    missing = [b["id"] for b in blocks if b["id"] not in notes]
    extra = [k for k in notes if k not in {b["id"] for b in blocks}]
    if missing:
        problems.append(f"{label}: {len(missing)} block(s) without annotation, e.g. {missing[:6]}")
    if extra:
        problems.append(f"{label}: {len(extra)} annotation(s) for unknown blocks: {extra[:6]}")
    for bid, note in notes.items():
        if set(note) == {"inherited"}:
            continue  # resolved against the single-target note it points at
        if note.get("force") not in FORCES:
            problems.append(f"{label}/{bid}: bad force {note.get('force')!r}")
        if note.get("owner") not in OWNERS:
            problems.append(f"{label}/{bid}: bad owner {note.get('owner')!r}")
        bad = [t for t in note.get("tags", []) if t not in TAGS]
        if bad:
            problems.append(f"{label}/{bid}: unknown tag(s) {bad}")
        if not note.get("title") or not note.get("note"):
            problems.append(f"{label}/{bid}: empty title or note")
    return problems if strict else [p for p in problems if "unknown" in p or "bad" in p]


FLOW_ARROWS = {"dispatch": "==>", "write": "-->", "read": "-.->", "terminate": "--x", "never": "-.-x"}
FLOW_SHAPES = {"agent": ('(["', '"])'), "code": ('[["', '"]]'), "state": ('[("', '")]'),
               "external": ('{{"', '"}}')}


def load_flow(raw_by_id: dict[str, str]) -> dict:
    """The Flow tab's authority graph. Every node name and every edge quote must appear
    verbatim in the block it cites, so the diagram cannot drift into paraphrase."""
    flow = json.loads((ANNOTATIONS / "flow_authority.json").read_text(encoding="utf-8"))
    ids = {n["id"] for n in flow["nodes"]}
    for n in flow["nodes"]:
        assert n["kind"] in FLOW_SHAPES, f"flow node {n['id']}: kind {n['kind']}"
        assert n["match"] in raw_by_id[n["block"]], f"flow node {n['id']}: {n['match']!r} not in {n['block']}"
        assert n.get("summary", "").strip(), f"flow node {n['id']}: missing summary"
    for e in flow["edges"]:
        assert e["from"] in ids and e["to"] in ids, f"flow edge {e['from']}->{e['to']}: unknown node"
        assert e["kind"] in FLOW_ARROWS, f"flow edge {e['from']}->{e['to']}: kind {e['kind']}"
        assert e["quote"] in raw_by_id[e["block"]], \
            f"flow edge {e['from']}->{e['to']}: quote not found verbatim in {e['block']}"

    lines = ["flowchart TB"]
    for n in flow["nodes"]:
        a, b = FLOW_SHAPES[n["kind"]]
        lines.append(f"  {n['id']}{a}{n['label']}{b}:::{n['kind']}")
    for i, e in enumerate(flow["edges"]):
        # No edge labels: they double the diagram's width. The rule list beside it carries
        # each edge's label and quote.
        # A read is already authored as an input, file first, so the arrowheads on a node
        # show what feeds it. (The sibling dissection of the pipeline authors the reader
        # first and reverses it here instead.)
        lines.append(f"  {e['from']} {FLOW_ARROWS[e['kind']]} {e['to']}")
        if e["kind"] == "never":
            lines.append(f"  linkStyle {i} stroke:#B42318,color:#B42318")
    lines += [f"  click {n['id']} flowNode" for n in flow["nodes"]]
    lines += [
        "  classDef agent fill:#EEF2FE,stroke:#2F4FD8,color:#12151A",
        "  classDef code fill:#F4F5F7,stroke:#12151A,color:#12151A",
        "  classDef state fill:#FBFBFC,stroke:#8B93A1,color:#12151A",
        "  classDef external fill:#FFF6E8,stroke:#8A5200,color:#12151A",
    ]
    flow["mermaid"] = "\n".join(lines)
    print(f"flow: {len(flow['nodes'])} nodes, {len(flow['edges'])} edges; every quote found verbatim")
    return flow


def main() -> int:
    strict = "--draft" not in sys.argv

    st_blocks, st_sections = read_blocks(SINGLE, "st")
    mt_blocks, mt_sections = read_blocks(MULTI, "mt")

    assert len(st_blocks) == EXPECT["st"], f"single blocks {len(st_blocks)} != {EXPECT['st']}"
    assert len(mt_blocks) == EXPECT["mt"], f"multi blocks {len(mt_blocks)} != {EXPECT['mt']}"
    assert len(st_sections) == EXPECT["sections"], f"single sections {len(st_sections)}"
    assert len(mt_sections) == EXPECT["sections"], f"multi sections {len(mt_sections)}"

    counter: dict[str, int] = {}
    for blk in st_blocks + mt_blocks:
        blk["html"] = tokenise(blk["raw"], counter)
        assert plain_text(blk["html"]) == blk["raw"], f"round-trip mismatch at {blk['id']}"

    st_notes = load_annotations("single_target")
    mt_authored = load_annotations("multi_target")
    mt_notes = inherit_annotations(st_blocks, st_notes, mt_blocks, mt_authored)
    problems = (validate(st_blocks, st_notes, "single", strict)
                + validate(mt_blocks, mt_notes, "multi", strict))

    n_inherited = sum(1 for n in mt_notes.values() if n.get("inherited"))
    print(f"blocks: single={len(st_blocks)} multi={len(mt_blocks)}  "
          f"sections={len(st_sections)}")
    print("entities: " + "  ".join(f"{k}={v}" for k, v in sorted(counter.items())))
    print(f"annotations: single={len(st_notes)}/{len(st_blocks)} "
          f"multi={len(mt_notes)}/{len(mt_blocks)} "
          f"({n_inherited} inherited, {len(mt_authored)} authored)")

    if problems:
        for p in problems[:20]:
            print(f"  ! {p}", file=sys.stderr)
        if strict:
            print(f"\n{len(problems)} problem(s); re-run with --draft to build anyway.",
                  file=sys.stderr)
            return 1

    slot_lines, slots = derive_slots()
    regions = align_documents(st_blocks, mt_blocks)

    known_ids = {b["id"] for b in st_blocks + mt_blocks}
    mechanical = {b for b, n in st_notes.items() if n.get("force") == "MECHANICAL"}
    pycode, pymeta = load_pycode(known_ids, mechanical)
    alias_pycode(pycode, mt_notes, regions)
    print(f"pycode: {pymeta['n_regions']} region(s) across {len(PYCODE_FILES)} module(s) "
          f"covering {len(mechanical)}/{len(mechanical)} MECHANICAL blocks; "
          + ", ".join(f"{k}={v}" for k, v in pymeta["kinds"].items() if v))
    print(f"        {pymeta['selftest']}; every region round-trips through the highlighter")

    n_prompts = len(list(SINGLE_DIR.glob("*.md")))
    print(f"template slots: {len(slot_lines)} varying line(s) across {n_prompts} prompts "
          f"-> {len(slots)} slot(s): " + ", ".join(f"{g['slot']}({g['n_lines']})" for g in slots))
    print(f"single<->multi changed regions: {len(regions)}")
    assert not any(g["slot"] == "OTHER" for g in slots), \
        "unclassified varying line(s) - a new template slot appeared upstream"

    payload = {
        "docs": {
            "single": {
                "label": "15-PGDH",
                "sub": "single target · 24 h · $10,000",
                "source": str(SINGLE.relative_to(ROOT)),
                "blocks": st_blocks,
                "sections": st_sections,
                "notes": st_notes,
            },
            "multi": {
                "label": "14 targets",
                "sub": "multi target · 48 h · $50,000",
                "source": str(MULTI.relative_to(ROOT)),
                "blocks": mt_blocks,
                "sections": mt_sections,
                "notes": mt_notes,
            },
        },
        "pycode": pycode,
        "pymeta": pymeta,
        "slots": slots,
        "slot_lines": slot_lines,
        "n_single_prompts": n_prompts,
        "regions": regions,
        "flow": load_flow({b["id"]: b["raw"] for b in st_blocks}),
        "vocab": {"tags": list(TAGS), "forces": list(FORCES), "owners": list(OWNERS)},
    }

    # The viewer keys annotations by block id across both documents in one flat map.
    all_notes = dict(st_notes)
    all_notes.update(mt_notes)

    rest = dict(payload)
    for key in ("single", "multi"):
        rest["docs"][key] = {k: v for k, v in rest["docs"][key].items() if k != "notes"}

    def embed(obj: object, **kw) -> str:
        """JSON for a <script type=application/json> block: '</' would end the element."""
        return json.dumps(obj, ensure_ascii=False, **kw).replace("</", "<\\/")

    annotations_json = embed(all_notes, indent=2)
    payload_json = embed(rest, separators=(",", ":"))
    assert "</" not in annotations_json and "</" not in payload_json, \
        "embedded JSON would terminate its <script> element early"

    template = (ROOT / "viewer.tmpl.html").read_text(encoding="utf-8")
    out = (template
           .replace("/*__ANNOTATIONS__*/", annotations_json)
           .replace("/*__PAYLOAD__*/", payload_json))
    OUT.write_text(out, encoding="utf-8")

    # Fidelity: pull the block text back out of the generated file and compare to source.
    embedded = re.search(r'id="payload">(.*?)</script>', out, re.S)
    assert embedded is not None, "payload block missing from generated HTML"
    written = json.loads(embedded.group(1).replace("<\\/", "</"))
    for key, path in (("single", SINGLE), ("multi", MULTI)):
        source = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        rendered = [plain_text(b["html"]) for b in written["docs"][key]["blocks"]]
        assert rendered == source, f"{key}: rendered text does not match {path.name}"
    print(f"fidelity: {len(st_blocks) + len(mt_blocks)} blocks round-trip from index.html")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
