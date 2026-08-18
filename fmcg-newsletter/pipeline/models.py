"""
Shared data model.

Every pipeline stage reads and writes this one shape, so stages can be
tested, swapped, or re-ordered independently. This mirrors how the
reference solution used a `state.py` module -- kept here for the same
reason (a single source of truth for the record shape) but as a plain
dataclass instead of framework-specific state, since nothing downstream
needs anything more than "a dict with known keys".
"""
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Article:
    # --- raw ingestion fields ---
    title: str
    source: str
    url: str
    published: str
    snippet: str

    # --- filled in by later stages ---
    cluster_id: Optional[int] = None          # which duplicate-cluster this belongs to
    is_primary: bool = False                  # the representative article of its cluster
    corroboration_count: int = 1              # how many distinct sources reported this cluster

    deal_type: Optional[str] = None           # M&A | Investment | Divestiture | JV/Partnership | None
    acquirer: Optional[str] = None
    target: Optional[str] = None
    deal_value: Optional[str] = None
    relevance_score: int = 0                  # 0-100, transparent rule-based score
    relevance_reasons: list = field(default_factory=list)

    credibility_tier: Optional[str] = None    # Tier 1 / Tier 2 / Tier 3
    credibility_score: int = 0                # 0-100
    credibility_reasons: list = field(default_factory=list)

    included_in_newsletter: bool = False
    exclusion_reason: Optional[str] = None

    def to_dict(self):
        return asdict(self)
