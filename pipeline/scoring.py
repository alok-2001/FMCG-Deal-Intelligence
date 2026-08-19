"""
Stage 3: Relevance scoring + Stage 4: Credibility scoring.

Difference from a two-pass "keyword gate then LLM classifier" design:
everything here is a transparent, additive rule-based score (0-100) with
a `reasons` list explaining exactly which signals fired. A reviewer (or
a business user reading the newsletter) can see *why* an item scored
84/100 instead of trusting an opaque model call. An LLM refinement hook
is included and OFF by default -- if OPENAI_API_KEY/ANTHROPIC_API_KEY is
set, it can nudge borderline cases, but nothing in this pipeline requires
an API key to run, which matters for a free/demo deployment.

Credibility likewise doesn't call out to a search API to "corroborate" --
it uses two signals that are already on the record for free: (a) which
tier the *publishing outlet* falls into, and (b) how many *independent
outlets* reported the same deal (from the dedupe stage's
corroboration_count). Both are visible and auditable; neither needs a
paid API key or an agent making its own tool-use decisions.
"""
import os
import re

FMCG_CATEGORY_TERMS = [
    "fmcg", "consumer goods", "packaged goods", "cpg", "beverage", "snack",
    "food and beverage", "personal care", "body care", "skincare", "haircare",
    "cosmetics", "home care", "household products", "grocery", "nutrition",
    "confectionery", "dairy", "beauty", "wellness", "hygiene", "cereal",
    "coffee", "tea", "pet food", "ingredients group",
]

DEAL_TYPE_RULES = [
    ("Divestiture", [r"\bdivest", r"\bsell(?:s|ing)?\s+(?:its|the)\b", r"\bsale\s+of\b", r"\bspin[\s-]?off"]),
    ("Investment", [r"\binvest(?:s|ing|ment)?\b", r"\braises?\b", r"\bstake\s+in\b", r"\bfunding\s+round\b", r"private equity"]),
    ("M&A", [r"\bacqui", r"\bbuys?\b", r"\bbought\b", r"\bmerger\b", r"\bmerges?\b", r"\btakeover\b"]),
    ("JV/Partnership", [r"\bjoint\s+venture\b", r"\bpartnership\b", r"\bteams?\s+up\b"]),
]

# Off-topic terms whose presence, without any FMCG category term nearby,
# strongly suggests the story isn't actually about the FMCG sector.
OFF_TOPIC_HINTS = [
    "cloud", "data center", "software", "chip", "semiconductor", "stadium",
    "sports team", "naming rights", "saas", "ai model", "crypto",
]


def _score_deal_type(text: str):
    for deal_type, patterns in DEAL_TYPE_RULES:
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return deal_type
    return None


def score_relevance(article, min_score_to_keep=45):
    """
    Sets article.deal_type, .relevance_score, .relevance_reasons,
    .included_in_newsletter (provisionally), .exclusion_reason.
    """
    text = f"{article.title} {article.snippet}".lower()
    score = 0
    reasons = []

    deal_type = _score_deal_type(text)
    if deal_type:
        score += 35
        reasons.append(f"Deal-type language found ('{deal_type}') (+35)")
        article.deal_type = deal_type
    else:
        reasons.append("No M&A/investment/divestiture verb pattern found (+0)")

    category_hits = [term for term in FMCG_CATEGORY_TERMS if term in text]
    if category_hits:
        bump = min(35, 12 * len(set(category_hits)))
        score += bump
        reasons.append(f"FMCG category terms: {', '.join(sorted(set(category_hits))[:4])} (+{bump})")
    else:
        reasons.append("No FMCG category terms found (+0)")

    if article.deal_value:
        score += 15
        reasons.append(f"Deal value stated ('{article.deal_value}') (+15)")

    if article.acquirer and article.target:
        score += 15
        reasons.append(f"Named acquirer/target extracted ({article.acquirer} -> {article.target}) (+15)")

    off_topic_hits = [term for term in OFF_TOPIC_HINTS if term in text]
    if off_topic_hits and not category_hits:
        score -= 40
        reasons.append(f"Off-topic terms with no FMCG context: {', '.join(off_topic_hits)} (-40)")

    score = max(0, min(100, score))
    article.relevance_score = score
    article.relevance_reasons = reasons

    if score < min_score_to_keep:
        article.included_in_newsletter = False
        article.exclusion_reason = f"Relevance score {score} below threshold {min_score_to_keep}"
    else:
        article.included_in_newsletter = True

    return article


# --- Credibility -----------------------------------------------------

TIER_1_DOMAINS = {
    "reuters", "bloomberg", "financial times", "wall street journal", "wsj",
    "the economic times", "business standard", "businesswire", "pr newswire",
    "moneycontrol", "livemint",
}
TIER_2_DOMAINS = {
    "foodbev media", "consumer goods technology", "marketscreener",
    "clarkston consulting", "just food", "food dive", "grocery dive",
    "stockhouse", "food business news",
}
# anything not in tier 1 or 2 falls to tier 3 (aggregators, blogs, unverified)


def score_credibility(article):
    """Sets article.credibility_tier, .credibility_score, .credibility_reasons."""
    source_lower = article.source.lower()
    source_compact = source_lower.replace(" ", "")
    reasons = []

    if any(name.replace(" ", "") in source_compact for name in TIER_1_DOMAINS):
        tier, base = "Tier 1 (wire service / major business press)", 70
    elif any(name.replace(" ", "") in source_compact for name in TIER_2_DOMAINS):
        tier, base = "Tier 2 (trade press / industry publication)", 50
    else:
        tier, base = "Tier 3 (aggregator / blog / unverified)", 25

    reasons.append(f"Publisher tier: {tier} (base {base})")
    score = base

    corroboration_bonus = min(30, (article.corroboration_count - 1) * 15)
    if corroboration_bonus:
        reasons.append(
            f"Corroborated by {article.corroboration_count} independent source(s) (+{corroboration_bonus})"
        )
    score += corroboration_bonus

    if article.corroboration_count <= 1 and tier.startswith("Tier 3"):
        reasons.append("Single unverified source, no independent corroboration (-15)")
        score -= 15

    score = max(0, min(100, score))
    article.credibility_tier = tier.split(" (")[0]
    article.credibility_score = score
    article.credibility_reasons = reasons
    return article


def maybe_llm_refine(article, client=None):
    """
    Optional refinement hook. Disabled unless an API key is present AND a
    client is explicitly passed in -- the base pipeline never requires
    this to run. Left as a clearly-marked extension point rather than a
    hard dependency, in contrast to a design where the LLM classifier is
    load-bearing for every item.
    """
    if client is None or not (os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        return article
    # Intentionally left unimplemented in the demo: wire up your model
    # client of choice here to nudge borderline (40-60) relevance scores.
    return article


def _aggregate_cluster_relevance(articles, min_score_to_keep):
    """
    Different outlets phrase the same deal differently -- one may name
    the category ("personal care brand"), another may not. Scoring each
    article in isolation would let the primary (most detailed) article's
    wording decide inclusion even when a duplicate clearly establishes
    FMCG relevance. Instead, the *best* signal anywhere in the cluster
    decides whether the underlying deal is relevant; the primary
    article's own text is still what gets displayed.
    """
    by_cluster = {}
    for art in articles:
        by_cluster.setdefault(art.cluster_id, []).append(art)

    for cid, members in by_cluster.items():
        best = max(members, key=lambda a: a.relevance_score)
        if best.relevance_score <= max(a.relevance_score for a in members if a.is_primary):
            continue
        primary = next((a for a in members if a.is_primary), None)
        if primary is None or best is primary:
            continue
        primary.relevance_score = best.relevance_score
        primary.relevance_reasons = primary.relevance_reasons + [
            f"Boosted to match a duplicate source ('{best.source}') that scored higher on the same deal"
        ]
        if primary.relevance_score >= min_score_to_keep:
            primary.included_in_newsletter = True
            primary.exclusion_reason = None


def run_scoring(articles, min_score_to_keep=45):
    for art in articles:
        score_relevance(art, min_score_to_keep=min_score_to_keep)
        score_credibility(art)
        # A low-credibility, single-source, unverified rumor shouldn't
        # make the newsletter even if the text matched deal language --
        # this is the "sensible credibility" requirement from the brief.
        if art.credibility_tier == "Tier 3" and art.corroboration_count <= 1 and art.credibility_score < 30:
            art.included_in_newsletter = False
            art.exclusion_reason = (art.exclusion_reason + "; " if art.exclusion_reason else "") + \
                "Single-source, low-credibility, uncorroborated report"

    _aggregate_cluster_relevance(articles, min_score_to_keep)
    return articles
