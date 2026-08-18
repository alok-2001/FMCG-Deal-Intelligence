"""
Lightweight smoke tests — no pytest fixtures/mocking needed since the
pipeline is pure, deterministic functions over plain dataclasses.
Run with: python -m pytest tests/ -q  (or just `python tests/test_pipeline.py`)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline import ingest, dedupe, scoring  # noqa: E402


def test_dedupe_merges_reworded_duplicates():
    articles = ingest.load_demo()
    dedupe.dedupe(articles)
    godrej = [a for a in articles if "Godrej" in a.title]
    assert len(godrej) == 2
    assert godrej[0].cluster_id == godrej[1].cluster_id
    assert sum(1 for a in godrej if a.is_primary) == 1
    assert godrej[0].corroboration_count == 2


def test_dedupe_keeps_distinct_deals_separate():
    articles = ingest.load_demo()
    dedupe.dedupe(articles)
    mars = next(a for a in articles if "Mars" in a.title)
    ferrero = next(a for a in articles if "Ferrero" in a.title)
    assert mars.cluster_id != ferrero.cluster_id


def test_scoring_excludes_off_topic_articles():
    articles = ingest.load_demo()
    dedupe.dedupe(articles)
    scoring.run_scoring(articles)
    stadium = next(a for a in articles if "stadium" in a.title.lower())
    assert stadium.included_in_newsletter is False


def test_scoring_excludes_unverified_rumor_despite_deal_language():
    articles = ingest.load_demo()
    dedupe.dedupe(articles)
    scoring.run_scoring(articles)
    rumor = next(a for a in articles if "Rumor" in a.title)
    assert rumor.included_in_newsletter is False
    assert "credibility" in (rumor.exclusion_reason or "").lower() or \
           "corroborat" in (rumor.exclusion_reason or "").lower() or \
           "source" in (rumor.exclusion_reason or "").lower()


def test_real_deals_survive_the_pipeline():
    articles = ingest.load_demo()
    dedupe.dedupe(articles)
    scoring.run_scoring(articles)
    included_titles = {a.title for a in articles if a.included_in_newsletter and a.is_primary}
    assert any("Ferrero" in t for t in included_titles)
    assert any("Saltair" in t for t in included_titles)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("All smoke tests passed.")
