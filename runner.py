"""
Orchestration: ingest -> dedupe -> score -> generate.

Kept intentionally as one straight-line function (not a graph/agent
framework) because every stage here is deterministic given its input --
there's no point in the pipeline where a model needs to decide *what to
do next*, only stages that transform data. That's a deliberate contrast
with an agent-loop design: simpler to run, cheaper (no LLM calls
required at all), and every decision is traceable to a rule you can read
in scoring.py, not a model's internal reasoning.
"""
import os

from datetime import datetime, timezone

from . import ingest, dedupe, scoring, newsletter
from .build_excel import build_excel


def run_pipeline(mode="demo", min_score_to_keep=45, queries=None, region_hint=None, output_dir=None):
    if mode == "demo":
        articles = ingest.load_demo()
    elif mode == "live":
        articles = ingest.fetch_live(queries=queries, region_hint=region_hint)
    else:
        raise ValueError(f"Unknown mode: {mode}")

    dedupe.dedupe(articles)
    scoring.run_scoring(articles, min_score_to_keep=min_score_to_keep)

    result = {
        "articles": articles,
        "included": [a for a in articles if a.included_in_newsletter and a.is_primary],
    }

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        result["markdown"] = newsletter.write_markdown(articles, os.path.join(output_dir, "newsletter.md"))
        result["json"] = newsletter.write_json(articles, os.path.join(output_dir, "newsletter.json"))
        newsletter.write_csv(articles, os.path.join(output_dir, "raw_data.csv"))
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        build_excel(result["included"], os.path.join(output_dir, "newsletter.xlsx"), generated_at)

    return result


if __name__ == "__main__":
    out = run_pipeline(mode="demo", output_dir=os.path.join(os.path.dirname(__file__), "..", "output"))
    print(f"Ingested: {len(out['articles'])} | Included in newsletter: {len(out['included'])}")
