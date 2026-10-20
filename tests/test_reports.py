"""Reports are built from live game data and export cleanly."""

from __future__ import annotations

import csv
import html as htmllib

import pytest

from riskascent.core.finance import cost_benefit
from riskascent.core.reporting import REPORT_KINDS, generate

from conftest import play_mission


@pytest.mark.parametrize("kind", list(REPORT_KINDS))
def test_every_report_kind_generates(game, kind):
    play_mission(game, "M01")
    game.advance_period("test")
    opts = {}
    if kind == "investment_proposal":
        r = game.list_risks()[0]
        cb = cost_benefit(300_000, 120_000, 150_000, 20_000)
        opts = {"risk_id": r["risk_id"], "title": "Sprinkler upgrade", "el_before": 300_000, "el_after": 120_000,
                "upfront": 150_000, "annual": 20_000, "years": 3, "rate": 0.08, "npv": cb.npv, "roi": cb.roi,
                "payback": cb.payback_years}
    if kind == "post_incident":
        ev = game.events(50)[0]
        opts = {"event": ev, "root_cause": "Checks were not scheduled", "lessons": "Schedule them"}
    html = generate(kind, game.report_data(), opts)
    assert html.startswith("<!doctype html>") and REPORT_KINDS[kind][0] in html
    assert htmllib.escape(game.org["name"]) in html
    assert "<script" not in html.lower(), "reports must be static"


def test_report_figures_match_the_register(game):
    from riskascent.core.risk_engine import prioritize
    html = generate("top_risks", game.report_data())
    for r in prioritize(game.list_risks(), game.appetite())[:10]:
        assert r["risk_id"] in html and htmllib.escape(r["title"]) in html


def test_investment_report_needs_inputs(game):
    with pytest.raises(ValueError):
        generate("investment_proposal", game.report_data(), {})


def test_register_csv_export(game, tmp_path):
    path = game.export_register_csv(tmp_path / "reg.csv")
    rows = list(csv.reader(path.open(encoding="utf-8")))
    assert len(rows) == len(game.list_risks()) + 1
    assert "Title" in rows[0] or "title" in [h.lower() for h in rows[0]]
