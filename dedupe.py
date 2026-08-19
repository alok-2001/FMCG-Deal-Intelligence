"""
Stage 2: De-duplication.

Difference from a TF-IDF/cosine-similarity approach: two articles about
the same deal often share almost no vocabulary ("Godrej Consumer
completes acquisition of FMCG business" vs "Godrej Consumer buys
Muuchstac maker for Rs 450 crore") because outlets paraphrase headlines
and one mentions the brand while the other mentions the price. Pure word
overlap under-clusters those. Instead this stage:

  1. Extracts the two company names and any deal amount from each
     title+snippet with light regex/heuristics ("X acquires/buys/to
     acquire Y", "$N billion/million", "Rs N crore").
  2. Clusters articles that share the same company pair (order-
     independent), even if the wording is completely different.
  3. As a fallback for articles where entity extraction is too noisy to
     trust, falls back to fuzzy title similarity (difflib) so near-
     identical headlines from syndication still merge.

This also has the side benefit of feeding Stage 3 (relevance/scoring)
pre-extracted acquirer/target/value fields for free, and feeding Stage 4
(credibility) a corroboration_count per cluster with no extra work.

No sklearn / embeddings dependency -- keeps the deploy footprint small
and every decision easy to explain in the newsletter's "why this was
grouped" trail, which matters more for a reviewer skimming logic than a
marginal recall gain would.

Two signals are combined with a union-find merge instead of relying on
either alone, because they fail in different, complementary ways:
  - entity-pair matching breaks when two outlets phrase the same deal
    around different nouns (one says "FMCG business", the other names
    the brand "Muuchstac") -- word overlap between the *titles* still
    tends to be low here too, so raw title similarity misses it as well.
  - a shared, distinctive proper-noun ("Godrej", "Trilogy", "Saltair",
    "TSG") almost never appears by coincidence across unrelated stories,
    so it acts as a robust fallback exactly where entity-pair and plain
    title-similarity both under-cluster.
"""
import re
from difflib import SequenceMatcher

# Generic business-story vocabulary that happens to be capitalized at the
# start of a sentence or in a headline, so it must not count as a
# "distinctive" signature token when checking for shared identity.
_SIGNATURE_STOPWORDS = {
    "the", "a", "an", "in", "to", "for", "of", "and", "its", "on", "from",
    "with", "by", "at", "as", "is", "are", "this", "that", "new", "after",
    "before", "amid", "under", "following", "consumer", "group", "products",
    "brands", "business", "solutions", "company", "companies", "ltd", "inc",
    "corp", "corporation", "limited", "private", "deal", "deals", "stake",
    "stakes", "majority", "acquisition", "acquires", "acquired", "acquire",
    "buys", "bought", "buy", "merger", "investment", "invests", "million",
    "billion", "crore", "rs", "usd", "fmcg", "pe", "completes", "completed",
    "position", "takes", "firm", "equity", "sale", "sells", "raises",
}


def _signature_tokens(title: str):
    """Distinctive capitalized tokens (likely company/brand names) in a
    title, with generic business vocabulary filtered out."""
    words = re.findall(r"[A-Za-z][A-Za-z']+", title)
    return {w for w in words if w[0].isupper() and w.lower() not in _SIGNATURE_STOPWORDS and len(w) > 2}

ACQUIRE_VERBS = r"(?:acquires?|acquired|to\s+acquire|buys?|bought|to\s+buy|completes?\s+acquisition\s+of|takes?\s+(?:a\s+)?majority\s+stake\s+in|invests?\s+in|to\s+invest\s+in|raises?)"

DEAL_VALUE_RE = re.compile(
    r"(?:USD|US\$|\$)\s?[\d,.]+\s?(?:billion|million|bn|mn|B|M)"
    r"|(?:Rs\.?|INR|₹)\s?[\d,.]+\s?crore",
    re.IGNORECASE,
)

PAIR_RE = re.compile(
    r"([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,4})\s+" + ACQUIRE_VERBS + r"\s+"
    r"(?:a\s+majority\s+stake\s+in\s+|majority\s+stake\s+in\s+)?"
    r"([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,4})",
)

STOPWORDS_IN_NAMES = {"The", "A", "An", "For", "In", "Of", "To"}


def _clean_name(name: str) -> str:
    tokens = [t for t in name.strip(" .,") .split() if t not in STOPWORDS_IN_NAMES]
    return " ".join(tokens[:4]).strip()


def extract_entities(title: str, snippet: str = ""):
    """Best-effort acquirer/target/value extraction. Returns (acquirer,
    target, value) with None for anything not confidently found."""
    text = f"{title}. {snippet}"
    acquirer = target = value = None

    match = PAIR_RE.search(title) or PAIR_RE.search(text)
    if match:
        acquirer = _clean_name(match.group(1))
        target = _clean_name(match.group(2))

    value_match = DEAL_VALUE_RE.search(text)
    if value_match:
        value = value_match.group(0).strip()

    return acquirer, target, value


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _pair_key(acquirer, target):
    if not acquirer or not target:
        return None
    # order-independent, case/space-insensitive key
    names = sorted([acquirer.lower().strip(), target.lower().strip()])
    return "|".join(names)


class _UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def dedupe(articles, title_similarity_threshold=0.55):
    """
    Mutates each Article in place: sets acquirer/target/deal_value,
    cluster_id, is_primary, corroboration_count. Returns the same list.

    Merges two articles if ANY of these fire (union-find over all pairs):
      1. same extracted acquirer/target pair
      2. at least one shared distinctive proper-noun signature token
      3. high raw title similarity (catches verbatim/syndicated copies)
    """
    n = len(articles)
    for art in articles:
        acquirer, target, value = extract_entities(art.title, art.snippet)
        art.acquirer, art.target, art.deal_value = acquirer, target, value

    signatures = [_signature_tokens(a.title) for a in articles]
    pair_keys = [_pair_key(a.acquirer, a.target) for a in articles]

    uf = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            same_pair = pair_keys[i] is not None and pair_keys[i] == pair_keys[j]
            shared_signature = bool(signatures[i] & signatures[j])
            similar_titles = _title_similarity(articles[i].title, articles[j].title) >= title_similarity_threshold
            if same_pair or shared_signature or similar_titles:
                uf.union(i, j)

    # Assign stable, zero-based cluster ids in first-seen order
    cluster_members = {}
    root_to_cid = {}
    next_cid = 0
    for i in range(n):
        root = uf.find(i)
        if root not in root_to_cid:
            root_to_cid[root] = next_cid
            next_cid += 1
        cid = root_to_cid[root]
        articles[i].cluster_id = cid
        cluster_members.setdefault(cid, []).append(i)

    # Pick a primary per cluster (longest snippet = most detail) and
    # stamp corroboration_count (distinct sources in the cluster)
    for cid, indices in cluster_members.items():
        best_idx = max(indices, key=lambda i: len(articles[i].snippet))
        articles[best_idx].is_primary = True
        distinct_sources = len({articles[i].source for i in indices})
        for i in indices:
            articles[i].corroboration_count = distinct_sources

    return articles


def primary_articles(articles):
    """Convenience: the one representative article per cluster."""
    return [a for a in articles if a.is_primary]
