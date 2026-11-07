"""Brain TUI tests: parse helpers, extended brain CLI JSON surface, pilot run.

Covers the completed brain screen work:
* ``--json`` output of the extended brain commands (status / insights / log /
  sessions / evolutions / genome) is parseable by the TUI helpers and carries
  the fields the tables need;
* NDJSON parsing accepts the one-JSON-array-per-line format the CLI emits;
* the brain screen populates its inline tables lazily, filters client-side,
  computes search relevance, opens the session detail modal with a live
  transcript, and exports CSV — all headlessly via Pilot.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from textual.coordinate import Coordinate
from textual.widgets import Button, DataTable, Input, RichLog, Static
from typer.testing import CliRunner

from raphael.multiagent.cli import app
from raphael.multiagent.tui.screens.brain import SessionDetailModal
from raphael.multiagent.tui.widgets import (
    export_rows,
    fmt_cell,
    parse_first_json,
    parse_ndjson,
    parse_ndjson_tables,
    populate_table_fixed,
    rows_fingerprint,
    truncate,
)

runner = CliRunner()


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("RAPHAEL_MA_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    return tmp_path / "home"


@pytest.fixture()
def populated_home(home):
    """One mock debate → 1 session, 3 turns, insights, outcomes."""
    assert runner.invoke(app, ["init"]).exit_code == 0
    r = runner.invoke(app, ["debate", "a test motion", "--rounds", "1", "-q", "--no-stream"])
    assert r.exit_code == 0, r.output
    return home


def _json_rows(output: str):
    """Parse the one-array-per-line JSON the CLI prints in --json mode."""
    rows = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("["):
            rows.extend(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# parse helpers


def test_parse_ndjson_flattens_json_arrays():
    text = '[{"id": 1}, {"id": 2}]\n[{"id": 3}]\n'
    assert [r["id"] for r in parse_ndjson(text)] == [1, 2, 3]


def test_parse_ndjson_still_accepts_object_lines():
    assert parse_ndjson('{"a": 1}\n{"a": 2}') == [{"a": 1}, {"a": 2}]


def test_parse_ndjson_ignores_garbage():
    assert parse_ndjson("not json\n\n[]") == []


def test_parse_ndjson_tables_keeps_boundaries():
    tables = parse_ndjson_tables('[{"a": 1}]\n[{"b": 2}, {"b": 3}]')
    assert tables == [[{"a": 1}], [{"b": 2}, {"b": 3}]]


def test_parse_first_json_pretty_printed_and_prefixed():
    text = 'noise before\n{\n  "x": {"y": [1, 2]},\n  "s": "brace } inside"\n}\ntail'
    assert parse_first_json(text) == {"x": {"y": [1, 2]}, "s": "brace } inside"}


def test_parse_first_json_none_on_garbage():
    assert parse_first_json("nothing here") is None
    assert parse_first_json("") is None


def test_fmt_cell_numeric_coercion_and_truncation():
    assert fmt_cell("0.68") == 0.68
    assert fmt_cell("7") == 7
    assert fmt_cell(True) == "✓"
    assert fmt_cell(None) == "—"
    assert fmt_cell("651afb700112") == "651afb700112"  # hex ids stay strings
    assert len(fmt_cell("x" * 100, 20)) == 20
    assert truncate("line\nbreak", 80) == "line break"


def test_rows_fingerprint_stable_and_sensitive():
    rows = [{"a": 1, "b": 2}]
    # dict key order must not matter, values must
    assert rows_fingerprint(rows) == rows_fingerprint([{"b": 2, "a": 1}])
    assert rows_fingerprint(rows) != rows_fingerprint([{"a": 1, "b": 3}])
    # row order matters: a re-ordered table is a changed table
    assert rows_fingerprint([{"a": 1}, {"b": 2}]) != rows_fingerprint([{"b": 2}, {"a": 1}])


def test_export_rows_json_and_csv(tmp_path):
    rows = [{"id": 1, "insight": "alpha"}, {"id": 2, "insight": "beta, comma"}]
    pj = export_rows(rows, "json", "insights", tmp_path)
    pc = export_rows(rows, "csv", "insights", tmp_path)
    assert pj is not None and pj.suffix == ".json"
    assert json.loads(pj.read_text()) == rows
    assert pc is not None
    csv_text = pc.read_text()
    assert "alpha" in csv_text and '"beta, comma"' in csv_text
    assert export_rows([], "json", "x", tmp_path) is None
    assert export_rows(rows, "xml", "x", tmp_path) is None


def test_populate_table_fixed_shapes_columns():
    from textual.app import App

    class TableApp(App):  # DataTable needs an active app context
        def compose(self):
            yield DataTable()

    app = TableApp()

    async def drive() -> None:
        async with app.run_test() as pilot:
            table = app.query_one(DataTable)
            cols = [("id", "ID", None), ("insight", "Insight", 10)]
            populate_table_fixed(table, [{"id": 1, "insight": "long text" * 5}], cols)
            assert [str(c.label) for c in table.ordered_columns] == ["ID", "Insight"]
            assert table.row_count == 1
            cell = table.get_cell_at(Coordinate(0, 1))
            assert cell.endswith("…") and len(cell) == 10
            # numeric cells stay numeric so sorting is numeric
            populate_table_fixed(table, [{"id": 1, "conf": 0.68}, {"id": 2, "conf": 0.9}],
                                 [("id", "ID", None), ("conf", "Conf", None)])
            conf_col = table.ordered_columns[1].key
            table.sort(conf_col, reverse=True)
            assert table.get_cell_at(Coordinate(0, 1)) == 0.9
            await pilot.pause(0.1)

    asyncio.run(drive())


# ---------------------------------------------------------------------------
# extended brain CLI JSON surface


def test_brain_status_json_has_db_and_genome_metrics(populated_home):
    r = runner.invoke(app, ["--json", "brain", "status"])
    assert r.exit_code == 0, r.output
    tables = parse_ndjson_tables(r.output)
    assert tables, "expected at least the metrics table"
    metrics = {row["metric"]: row["value"] for row in tables[0]}
    for key in (
        "db path", "db size", "wal", "sessions", "active sessions",
        "journal turns", "insights (active/total)", "outcomes",
        "evolutions (total/active)", "last evolution", "genome hash",
    ):
        assert key in metrics, f"missing metric: {key}"
    assert "brain.db" in str(metrics["db path"])
    assert metrics["wal"] == "wal"
    assert metrics["sessions"] == 1
    assert len(str(metrics["genome hash"])) == 12
    # second table: active persona genome
    assert len(tables) >= 2 and tables[1] and "persona" in tables[1][0]


def test_brain_insights_json_rich_fields(populated_home):
    r = runner.invoke(app, ["--json", "brain", "insights", "--limit", "10"])
    assert r.exit_code == 0, r.output
    rows = _json_rows(r.output)
    assert rows, "expected at least one insight after a debate"
    first = rows[0]
    for key in ("id", "conf", "weight", "used", "✓/✗", "active", "created", "insight"):
        assert key in first, f"missing insight field: {key}"
    assert isinstance(first["conf"], float)
    assert isinstance(first["active"], bool)
    assert first["created"]


def test_brain_search_json_numeric_scores(populated_home):
    r = runner.invoke(app, ["--json", "brain", "search", "risk framing", "-k", "3"])
    assert r.exit_code == 0, r.output
    rows = _json_rows(r.output)
    if rows:  # recall may legitimately return nothing for odd queries
        assert isinstance(rows[0]["conf"], float)
        assert isinstance(rows[0]["sim"], float)


def test_brain_log_json_timestamp_and_full_session(populated_home):
    r = runner.invoke(app, ["--json", "brain", "log", "--last", "5"])
    assert r.exit_code == 0, r.output
    rows = _json_rows(r.output)
    assert rows
    first = rows[0]
    for key in ("at", "session", "agent", "role", "phase", "excerpt"):
        assert key in first, f"missing log field: {key}"
    assert len(first["session"]) == 12  # full id, not the [:8] human truncation
    # the full id must actually drill down
    drill = runner.invoke(app, ["--json", "brain", "log", "--session", first["session"]])
    assert drill.exit_code == 0
    assert _json_rows(drill.output)


def test_brain_sessions_json_started_finished_full_id(populated_home):
    r = runner.invoke(app, ["--json", "brain", "sessions"])
    assert r.exit_code == 0, r.output
    rows = _json_rows(r.output)
    assert rows
    first = rows[0]
    for key in ("id", "kind", "topic", "mode", "started", "finished", "verdict"):
        assert key in first, f"missing session field: {key}"
    assert len(first["id"]) == 12
    assert first["finished"]  # the debate closed the session


def test_brain_evolutions_and_genome_commands(populated_home):
    r = runner.invoke(app, ["--json", "brain", "evolutions"])
    assert r.exit_code == 0, r.output
    # empty history prints the CLI's conventional placeholder row
    assert _json_rows(r.output) == [{"id": "(none)"}]

    g = runner.invoke(app, ["--json", "brain", "genome"])
    assert g.exit_code == 0, g.output
    tables = [json.loads(line) for line in g.output.splitlines() if line.startswith("[")]
    personas, strategy = tables[0], tables[1]
    assert len(personas) == 10  # seeded genome
    assert {"persona", "version", "origin", "prompt_sha"} <= set(personas[0])
    assert strategy == [{"key": "(all defaults)", "value": "—"}]


# ---------------------------------------------------------------------------
# pilot: the brain screen itself


async def _wait_idle(app, pilot, table=None, timeout_s: float = 20.0) -> None:
    """Wait until the app settles: not busy (after a settle pause) and the
    optional table has rows. The settle pause avoids racing the mount-time
    command that has not flipped `busy` on yet."""
    await pilot.pause(0.5)
    loops = int(timeout_s / 0.25)
    for _ in range(loops):
        await pilot.pause(0.25)
        if not app.state.busy and (table is None or table.row_count > 0):
            return
    await pilot.pause(0.5)


async def _switch_tab(pilot, screen, label: str) -> None:
    for tab in screen.query("TabbedContent Tabs Tab"):
        if str(tab.label) == label:
            await pilot.click(tab)
            await pilot.pause(0.2)
            return
    raise AssertionError(f"tab not found: {label}")


async def test_brain_screen_tables_filters_modal_and_export(populated_home):
    from raphael.multiagent.tui.app import RaphaelTUI

    app = RaphaelTUI(home=str(populated_home))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("f6")
        await _wait_idle(app, pilot)
        screen = app.screen
        assert type(screen).__name__ == "BrainScreen"

        # status panel + genome table populated from `brain status`
        assert "brain.db" in str(screen.query_one("#status-panel", Static).render())
        assert screen.query_one("#status-genome-table", DataTable).row_count == 10

        # status strip shows brain metrics while on the brain screen
        assert "insights" in str(screen.query_one("#strip-brain", Static).render())

        # lazy load on activation: insights
        await _switch_tab(pilot, screen, "Insights")
        ins_table = screen.query_one("#insights-table", DataTable)
        await _wait_idle(app, pilot, table=ins_table)
        assert ins_table.row_count >= 1

        # client-side filter narrows the view (unknown term → 0 rows)
        assert ins_table.row_count >= 1
        screen.query_one("#ins-filter", Input).value = "zzz-no-such-insight"
        await pilot.pause(0.3)
        assert ins_table.row_count == 0
        screen.query_one("#ins-filter", Input).value = ""
        await pilot.pause(0.3)
        assert ins_table.row_count >= 1

        # search tab: relevance column = sim × conf, sorted desc
        await _switch_tab(pilot, screen, "Search")
        screen.query_one("#srch-query", Input).value = "risk framing"
        await pilot.click("#btn-search")
        srch = screen.query_one("#srch-results", DataTable)
        await _wait_idle(app, pilot, table=srch)
        assert srch.row_count >= 1
        headers = [str(c.label) for c in srch.ordered_columns]
        assert headers == ["ID", "Insight", "Conf", "Sim", "Relevance"]
        relevances = [
            srch.get_cell_at(Coordinate(row, 4)) for row in range(srch.row_count)
            if isinstance(srch.get_cell_at(Coordinate(row, 4)), (int, float))
        ]
        assert relevances == sorted(relevances, reverse=True)
        assert "relevance" in str(screen.query_one("#srch-hint", Static).render())

        # sessions tab: row selection → detail modal → live transcript
        await _switch_tab(pilot, screen, "Sessions")
        sess = screen.query_one("#sess-table", DataTable)
        await _wait_idle(app, pilot, table=sess)
        assert sess.row_count == 1
        sess.post_message(
            DataTable.RowSelected(sess, 0, sess.ordered_rows[0].key)
        )
        await pilot.pause(0.4)
        modal = app.screen
        assert isinstance(modal, SessionDetailModal)
        modal.query_one("#detail-load-turns", Button).press()
        await _wait_idle(app, pilot)
        await pilot.pause(0.3)
        detail_log = modal.query_one("#detail-log", RichLog)
        assert len(detail_log.lines) >= 1  # transcript streamed in

        # export keybinding writes a CSV under <home>/exports for this tab
        await pilot.press("escape")
        await pilot.pause(0.2)
        await pilot.press("x")
        await pilot.pause(0.4)
        exports = sorted((populated_home / "exports").glob("sessions-*.csv"))
        assert exports, "expected an exported CSV for the sessions tab"
