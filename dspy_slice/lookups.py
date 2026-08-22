"""The lookups st-250 requires, as DSPy tools, over a logbook that records them.

st-250: "Before concluding any named tool, model, or resource is unavailable, query
HuggingFace, GitHub, PyPI, the skill catalog, and the External Resource Corpus directly
... declare unavailable only after those queries, and log the exact queries with the
conclusion."

The logbook is the part that matters. st-218 says every external identifier in a
deliverable must be "the literal output of a fetch or lookup executed in the same
session that wrote it", which is only checkable if something recorded what was fetched.
So the tools are thin, and the ledger under them is the actual mechanism: `metric.py`
scores the model's citations against it.

These lookups are stubbed the same way `pycode/external.py` stubs Modal and Slack --
this package is a reconstruction for reading, not a client for HuggingFace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import dspy

# The five indexes st-250 names. All five must be queried before UNAVAILABLE is a
# permitted conclusion; four is not four fifths of the rule, it is a violation.
REQUIRED_INDEXES: tuple[str, ...] = (
    "huggingface", "github", "pypi", "skill_catalog", "corpus",
)

# Corpus folder st-216 points at for method papers.
PAPERS = "07 Prompt-Cited Papers"

_IDENTIFIER = re.compile(
    r"\b(?:10\.\d{4,9}/\S+|PMID:\d+|[A-Z0-9]{4}(?=\s|$)|"
    r"https?://\S+|[\w.-]+/[\w.-]+)\b"
)


@dataclass
class Logbook:
    """What this session actually fetched. The provenance root for st-218."""

    queries: list[tuple[str, str]] = field(default_factory=list)
    artifacts: set[str] = field(default_factory=set)

    def reset(self) -> None:
        self.queries.clear()
        self.artifacts.clear()

    def record(self, index: str, query: str, result: str) -> str:
        self.queries.append((index, query))
        for ident in _IDENTIFIER.findall(result):
            self.artifacts.add(f"{index}:{ident}")
        self.artifacts.add(f"{index}:{query}")
        return result

    def indexes_queried(self) -> set[str]:
        return {index for index, _ in self.queries}

    def satisfies_unavailability_rule(self) -> bool:
        """st-250, fail-closed: every named index, or the conclusion is not available."""
        return set(REQUIRED_INDEXES) <= self.indexes_queried()

    def consulted_method_sources(self) -> bool:
        """st-216: the paper AND the source, before declaring a method broken."""
        return any(index == "corpus" for index, _ in self.queries) and any(
            index == "github" for index, _ in self.queries
        )


# ── the tools themselves ──────────────────────────────────────────────────────────────
#
# A fixture stands in for the network. Each entry is what that index would return; the
# logbook mines identifiers out of it, so a citation can be checked against a fetch.

FIXTURE: dict[tuple[str, str], str] = {
    ("corpus", "Protenix v2"):
        f"{PAPERS}/protenix-v2.pdf -- 10.1101/2025.01.0001 "
        "Sec 3.2: per-token PAE is emitted only when atom confidence heads are enabled; "
        "the CLI exposes this as --need_atom_confidence.",
    ("github", "bytedance/Protenix"):
        "bytedance/Protenix README: v2.0.0 renamed --use_msa_server to --use_msa. "
        "Defaults are 200 diffusion steps and bf16; do not pass --step or --dtype.",
    ("pypi", "protenix"):
        "pypi.org/project/protenix 2.0.0 requires cuda>=12.1 at build time.",
    ("huggingface", "TMF001/pxdesign-weights"):
        "huggingface.co/TMF001/pxdesign-weights -- 6 files, sha256 manifest present.",
    ("skill_catalog", "protenix"):
        "no skill entry for protenix.",
    ("corpus", "ESMFold2"):
        f"{PAPERS}/esmfold2.pdf -- 10.1101/2024.11.0002 "
        "Sec 2: the -Fast checkpoint ships without an MSA encoder and is "
        "single-sequence only.",
    ("github", "Biohub/esm"):
        "Biohub/esm README: install from git; the PyPI package named 'esm' is an "
        "unrelated project and does not contain ESMFold2.",
    ("pypi", "esm"):
        "pypi.org/project/esm 2.0.0 -- Evolutionary Scale Modeling, no ESMFold2 module.",
    ("huggingface", "biohub/ESMFold2"):
        "huggingface.co/biohub/ESMFold2 -- MIT, ungated.",
    ("skill_catalog", "esmfold2"):
        "no skill entry for esmfold2.",
}


def _fixture(index: str, query: str) -> str:
    for (idx, key), text in FIXTURE.items():
        if idx == index and (key.lower() in query.lower() or query.lower() in key.lower()):
            return text
    return f"{index}: no result for {query!r}."


def make_tools(log: Logbook) -> list[dspy.Tool]:
    """One tool per index named in st-250, plus the corpus paper reader from st-216."""

    def search_huggingface(query: str) -> str:
        """Search HuggingFace for a model, dataset or weights repo."""
        return log.record("huggingface", query, _fixture("huggingface", query))

    def search_github(query: str) -> str:
        """Read a GitHub repository's README and release notes."""
        return log.record("github", query, _fixture("github", query))

    def search_pypi(query: str) -> str:
        """Look up a package on PyPI, including its build requirements."""
        return log.record("pypi", query, _fixture("pypi", query))

    def search_skill_catalog(query: str) -> str:
        """Search the harness skill catalog for an existing wrapper."""
        return log.record("skill_catalog", query, _fixture("skill_catalog", query))

    def read_method_paper(method: str) -> str:
        """Read a method's own paper from the External Resource Corpus (st-216)."""
        return log.record("corpus", method, _fixture("corpus", method))

    return [
        dspy.Tool(search_huggingface),
        dspy.Tool(search_github),
        dspy.Tool(search_pypi),
        dspy.Tool(search_skill_catalog),
        dspy.Tool(read_method_paper),
    ]
