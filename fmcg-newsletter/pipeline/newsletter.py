"""
Stage 5: Newsletter generation.

Takes the scored, de-duplicated primary articles and produces:
  - a short structured Markdown newsletter
  - a full JSON record of every article + every stage's reasoning
  - a flat CSV of the raw per-article data
"""

import csv
import json
import re
from datetime import datetime, timezone


def _clean_text(text):
    """Clean article text and remove accidental Markdown formatting."""

    if text is None:
        return ""

    text = str(text)

    # Remove Markdown formatting characters
    text = text.replace("**", "")
    text = text.replace("__", "")
    text = text.replace("*", "")
    text = text.replace("`", "")

    # Replace underscores with spaces
    text = text.replace("_", " ")

    # Remove extra spaces
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def _fmt_deal(article):
    """Create a clean headline for a deal."""

    acquirer = _clean_text(article.acquirer)
    target = _clean_text(article.target)
    title = _clean_text(article.title)
    deal_value = _clean_text(article.deal_value)

    # Prefer acquirer and target when both are available
    if acquirer and target:
        headline = f"{acquirer} → {target}"
    else:
        headline = title

    # Add deal value only if it is not already present in headline
    if deal_value and deal_value.lower() not in headline.lower():
        headline = f"{headline} ({deal_value})"

    return headline


def build_newsletter_markdown(included_articles, generated_at=None):

    generated_at = generated_at or datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    by_type = {}

    for art in included_articles:
        deal_type = _clean_text(art.deal_type) or "Other"
        by_type.setdefault(deal_type, []).append(art)

    lines = [
        "# FMCG Deal Intelligence Newsletter",
        f"Generated: {generated_at} | {len(included_articles)} deals from the last run",
        "",
    ]

    order = [
        "M&A",
        "Investment",
        "Divestiture",
        "JV/Partnership",
        "Other",
    ]

    for deal_type in order:

        items = by_type.get(deal_type)

        if not items:
            continue

        lines.append(f"## {deal_type}")
        lines.append("")

        for art in sorted(
            items,
            key=lambda a: a.relevance_score,
            reverse=True
        ):

            headline = _fmt_deal(art)
            snippet = _clean_text(art.snippet)
            source = _clean_text(art.source)

            # Clean source URL
            url = str(art.url).strip() if art.url else ""

            lines.append(f"### {headline}")
            lines.append("")

            if snippet:
                lines.append(snippet)
                lines.append("")

            source_text = (
                f"Sources: {art.corroboration_count} | "
                f"Credibility: {art.credibility_tier} "
                f"({art.credibility_score}/100) | "
                f"Relevance: {art.relevance_score}/100"
            )

            if source and url:
                source_text += f" | [{source}]({url})"

            lines.append(source_text)
            lines.append("")

    return "\n".join(lines)


def build_json_record(all_articles, generated_at=None):

    generated_at = generated_at or datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    return {
        "generated_at": generated_at,
        "total_ingested": len(all_articles),
        "total_included": sum(
            1
            for a in all_articles
            if a.included_in_newsletter and a.is_primary
        ),
        "articles": [
            a.to_dict()
            for a in all_articles
        ],
    }


def write_csv(all_articles, path):

    fieldnames = [
        "title",
        "source",
        "url",
        "published",
        "acquirer",
        "target",
        "deal_value",
        "deal_type",
        "cluster_id",
        "is_primary",
        "corroboration_count",
        "relevance_score",
        "credibility_tier",
        "credibility_score",
        "included_in_newsletter",
        "exclusion_reason",
    ]

    with open(
        path,
        "w",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames
        )

        writer.writeheader()

        for art in all_articles:

            row = {
                k: getattr(art, k)
                for k in fieldnames
            }

            writer.writerow(row)


def write_markdown(all_articles, path):

    included = [
        a
        for a in all_articles
        if a.included_in_newsletter and a.is_primary
    ]

    md = build_newsletter_markdown(included)

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:
        f.write(md)

    return md


def write_json(all_articles, path):

    record = build_json_record(all_articles)

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            record,
            f,
            indent=2
        )

    return record
