# FMCG Deal Intelligence Newsletter

A deterministic pipeline that turns public FMCG news into a short, structured
newsletter of recent M&A, investment, divestiture, and partnership activity —
with every de-duplication and scoring decision left visible and explainable,
rather than hidden inside a model call.

![architecture](assets/architecture.png) 

Try the application here: [Open FMCG Deal Intelligence App](https://fmcg-deal-intelligence-g8tfrgl4vxnzgsvstpmu5g.streamlit.app/)

## What it does

```text
ingest → dedupe → score (relevance + credibility) → generate → Streamlit app
```

1. **Ingest** — pulls FMCG deal news from multiple RSS sources (Google News
   and Bing News), or loads a local demo dataset. At this stage, the pipeline
   only collects article data; it does not yet decide whether an article is
   relevant, credible, or a duplicate.

2. **Dedupe** — extracts deal entities where possible, then groups articles
   covering the same deal using three complementary signals: the same
   acquirer/target pair, a shared distinctive proper-noun token, or sufficiently
   similar raw titles. Matching articles are connected with a Union-Find merge.

3. **Score** — every article gets a transparent 0–100 **relevance** score and
   a 0–100 **credibility** score, each with a plain-English list of reasons.
   Relevance is based on deal language, FMCG context, deal value, entities, and
   off-topic penalties. Credibility combines publisher tier and corroboration.
   No LLM call is required for the base pipeline to run.

4. **Generate** — assembles the surviving primary deals into a newsletter in
   four formats: Markdown, Excel, JSON, and CSV.

5. **App** — a Streamlit UI with a Newsletter tab, a Scoring trail tab showing
   why each item was included, excluded, or merged, and a Raw data tab.

## Quickstart

```bash
git clone <this-repo-url>
cd fmcg-newsletter
python -m venv .venv
```

Activate the environment:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

Install dependencies and run the app:

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app opens in **Demo mode** by default — it runs the full pipeline on a
small set of FMCG deal examples stored in `data/demo_seed.json`, including
intentional duplicates and low-relevance/low-credibility cases so the later
stages can be inspected with zero network calls and zero API keys.

Switch to **Live fetch** in the sidebar to pull current results from the
configured RSS feeds. The live path requires outbound internet access.

Run the pipeline directly without the UI:

```bash
python -m pipeline.runner
# writes output/newsletter.md, newsletter.json, newsletter.xlsx, raw_data.csv
```

## Configuration

Copy `.env.example` to `.env` if you want to use optional environment-based
configuration. **Nothing is required** for the demo to run — the base pipeline
is entirely rule-based.

The code also contains an optional, currently unimplemented LLM refinement
hook for borderline relevance cases. It is not part of the normal pipeline
and the project does not require an API key or LLM dependency.

## Pipeline logic, briefly

**Shared article model** (`pipeline/models.py`) defines one `Article` record
that moves through the whole pipeline. It starts with raw fields such as
`title`, `source`, `url`, `published`, and `snippet`, then later stages add
cluster information, extracted deal fields, scores, reasons, and the final
include/exclude decision. `to_dict()` provides the common representation used
by the JSON, CSV, and Excel outputs.

**De-duplication** (`pipeline/dedupe.py`) first performs best-effort
regex/heuristic extraction of the acquirer, target, and deal value from the
title and snippet. It then merges two articles if *any* of three signals fire:

- they extract to the same acquirer/target pair, using an order-independent
  pair key;
- they share at least one distinctive capitalized signature token after generic
  business words are filtered out; or
- their raw titles have a `SequenceMatcher` similarity of at least `0.55`,
  which helps catch near-identical or syndicated headlines.

The merge is performed with **Union-Find**, so connected articles become one
duplicate cluster. For each cluster, the article with the **longest snippet**
is selected as the `is_primary` representative, and
`corroboration_count` is set to the number of distinct source labels present
in that cluster.

This implementation does **not** use TF-IDF, cosine similarity, embeddings, or
a vector database.

**Relevance scoring** (`pipeline/scoring.py`) is an additive 0–100 rule-based
score. It adds:

- **+35** when deal-type language identifies M&A, Investment, Divestiture, or
  JV/Partnership;
- up to **+35** for FMCG category terms;
- **+15** when a deal value is extracted; and
- **+15** when both acquirer and target are extracted.

If off-topic terms such as software, cloud, semiconductor, or crypto appear
without FMCG category context, the score receives a **−40** penalty. The score
is capped between 0 and 100, and every triggered rule is stored in
`relevance_reasons`.

An article initially clears the relevance gate when its score is at least the
configured threshold (45 by default).

**Cluster-level relevance handling** prevents a valid deal from being missed
only because the chosen primary article uses weaker wording. After all articles
are scored, the pipeline checks each duplicate cluster. If a duplicate article
has a higher relevance score than the primary representative, the primary
article is boosted to that higher score and receives a recorded explanation.
The primary article's own text is still what appears in the newsletter.

**Credibility scoring** starts from the article's publisher tier:

- **Tier 1** — configured major wire services and business press, base score 70;
- **Tier 2** — configured trade and industry publications, base score 50;
- **Tier 3** — sources not matched by the first two lists, base score 25.

The score then receives up to **+30** from corroboration, calculated as
15 points for each additional distinct source, capped at 30. A single-source
Tier 3 item receives a further **−15** penalty. Every decision is recorded in
`credibility_reasons`.

A Tier 3 article with no corroboration and a credibility score below 30 is
explicitly excluded, even if its relevance score otherwise passed the
threshold.

**Selection** is therefore based on the scoring rules above. The final
newsletter includes only articles where both:

```text
included_in_newsletter = True
is_primary = True
```

The non-primary duplicates are retained in the JSON and CSV outputs so the
full decision trail remains inspectable.

**Generation** (`pipeline/newsletter.py`) creates:

- **Markdown** — a short newsletter grouped by deal type and sorted within
  each group by relevance score;
- **JSON** — every article and all of its stage outputs, including scores,
  reasons, cluster information, and inclusion status;
- **CSV** — a flat article-level export of the main raw and scored fields.

**Excel generation** (`pipeline/build_excel.py`) creates the requested styled
`.xlsx` newsletter. It includes deal type, acquirer, target, deal value,
headline, summary, source count, credibility tier and score, relevance score,
publisher, link, and published date, along with styled headers, configured
column widths, wrapped text, frozen panes, and auto-filtering.

**Orchestration** (`pipeline/runner.py`) runs the stages in a fixed sequence:

```text
ingest → dedupe → score → generate
```

The pipeline is intentionally straight-line rather than agent-driven: each
stage has a predefined transformation, and no model is required to decide what
to do next. This keeps the base implementation deterministic, inexpensive, and
easy to trace back to readable rules in the code.

## Project structure

```text
fmcg-newsletter/
├── app.py                   Streamlit front end
├── pipeline/
│   ├── models.py            shared Article record
│   ├── ingest.py            multi-source RSS + demo-mode loader
│   ├── dedupe.py            entity extraction + duplicate clustering
│   ├── scoring.py           relevance + credibility scoring
│   ├── newsletter.py        Markdown / JSON / CSV generation
│   ├── build_excel.py       styled .xlsx newsletter
│   └── runner.py            pipeline orchestration
├── data/
│   └── demo_seed.json       FMCG deal data used for the offline demo
├── output/                  generated newsletter files
├── sample_output/           example generated outputs
├── tests/
│   └── test_pipeline.py     pipeline tests
├── assets/
│   └── architecture.png
├── requirements.txt
└── .env.example
```

## Tech stack

Python, Streamlit, `feedparser`, `openpyxl`, and `pandas`.

The base pipeline does not require a vector database, embeddings, TF-IDF,
scikit-learn, a machine learning model, an LLM, or an agent framework.

## Known limitations

**Entity extraction** is regex/heuristic-based rather than a dedicated NER
model, so unusual sentence structures can sometimes produce incomplete or
incorrect acquirer/target extraction.

**RSS snippets** can be short and may not contain all the deal context found
in the full article. Because relevance scoring uses the available title and
snippet, some otherwise relevant deals may score below the threshold when the
strongest context is missing.

Both are natural next improvements: replace the heuristic extractor with a
dedicated NER approach, or fetch richer article text before scoring.

## Deploying

**Streamlit Community Cloud**: push this repo and point Streamlit Cloud at
`app.py`. Demo mode requires no secrets.

**Vercel**: the pipeline itself is independent of Streamlit and can be wrapped
in a small FastAPI or Flask application and deployed as a Python serverless
function, subject to the deployment environment supporting the required RSS
network access and dependencies.

## Deliverables checklist (per assignment)

- [x] Demo app link — [Open FMCG Deal Intelligence App](https://fmcg-deal-intelligence-g8tfrgl4vxnzgsvstpmu5g.streamlit.app/)
- [x] GitHub repository — add your repository URL
- [x] Raw data in CSV/JSON — `output/raw_data.csv`, `output/newsletter.json`
- [x] Pipeline explanation with de-duplication and scoring logic — this README
      plus inline comments in `pipeline/dedupe.py` and `pipeline/scoring.py`
- [x] Structured newsletter in Excel — `output/newsletter.xlsx`
