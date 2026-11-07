"""Mission-control theme for the raphael-ma TUI.

Near-black background, amber + cyan accents, boxed panels, monospace feel.
All colors are declared here so the whole console can be re-skinned in one
place.

v2 polish pass: visible scrollbars, zebra-striped tables with amber headers
and a cyan row cursor, highlighted active tabs, per-variant buttons, focus
rings on every input, animated status strip chips, and dedicated styles for
the run screens (chat bubbles, debate verdict, community synthesis, teams
plan preview).
"""

from __future__ import annotations

PALETTE = {
    "bg": "#0b0e14",
    "panel": "#11151f",
    "panel2": "#161b27",
    "panel3": "#1d2433",
    "border": "#2a3242",
    "border2": "#3a4356",
    "amber": "#ffb454",
    "cyan": "#39bae6",
    "red": "#e05661",
    "green": "#3fd084",
    "purple": "#d2a6ff",
    "dim": "#8b93a7",
    "fog": "#d5dbe6",
}

MISSION_CONTROL_CSS = """
$bg: #0b0e14;
$panel: #11151f;
$panel2: #161b27;
$panel3: #1d2433;
$border: #2a3242;
$border2: #3a4356;
$amber: #ffb454;
$cyan: #39bae6;
$red: #e05661;
$green: #3fd084;
$purple: #d2a6ff;
$dim: #8b93a7;
$fog: #d5dbe6;

Screen {
    background: $bg;
    color: $fog;
}

/* scrollbars: always visible, never loud ------------------------------- */
VerticalScroll, HorizontalScroll, RichLog, DataTable, OptionList, TextArea {
    scrollbar-color: $border2;
    scrollbar-background: $panel;
    scrollbar-size-vertical: 1;
}

/* ---- status strip --------------------------------------------------- */
#strip { height: 1; background: $panel; }
.strip-item { width: auto; color: $dim; background: $panel; padding: 0 1; }
#strip-busy { color: $amber; }
#strip-clock { color: $dim; text-style: bold; }

.badge { width: auto; padding: 0 2; background: $panel2; color: $dim; text-style: bold; }
.badge.mock { color: $cyan; }
.badge.live { color: $red; background: #2a1216; }
.badge.warn { color: $amber; }
.badge.ok { color: $green; }
.badge.danger { color: $red; background: #2a1216; }

/* ---- chrome ---------------------------------------------------------- */
#body { height: 1fr; padding: 0 1; }
#cmdbar { height: 1; color: $cyan; background: $panel2; padding: 0 1; text-style: bold; }
#output { height: 34%; border: round $border; background: $panel; margin-top: 1; }
#result { height: 2; padding: 0 1; }
.result.run { color: $amber; }
.result.ok { color: $green; }
.result.fail { color: $red; }

/* ---- panels ---------------------------------------------------------- */
.panel { border: round $border; background: $panel; padding: 0 1; margin: 0 1 1 0; height: auto; }
.panel.danger { border: heavy $red; background: #2a1216; color: $fog; }
.section-label { color: $amber; text-style: bold; margin: 1 0 0 0; }
.hint-label { color: $dim; margin: 1 0 0 0; }

/* ---- forms ----------------------------------------------------------- */
.form-row { height: auto; margin: 0 0 1 0; }
.form-row Label { width: auto; padding: 1 1 0 0; color: $dim; }
.form-row Input { width: 1fr; }
.form-row Select { width: 26; }
.form-row Checkbox { width: auto; margin: 1 1 0 1; }
.field-label { width: 14; color: $dim; padding: 1 1 0 0; }

Button { background: $panel2; color: $amber; border: round $border; margin: 0 1 0 0; min-width: 6; }
Button:hover { background: $panel3; color: $fog; }
Button:focus { text-style: bold; border: tall $amber; }
Button.-primary { color: $cyan; border: round #1f4a5c; }
Button.-warning { color: $amber; border: round #5c451f; }
Button.-error { color: $red; border: round #4a2027; }
Button.-success { color: $green; border: round #1f5c3a; }
Button.danger { color: $red; border: round #4a2027; }

Input { background: $panel2; border: round $border; color: $fog; }
Input:focus { border: tall $amber; background: $panel3; }
Input > .input--placeholder { color: #5a6275; }
Select { background: $panel2; border: round $border; }
Select:focus { border: tall $amber; }
Checkbox { background: $panel; }
Checkbox:focus { text-style: bold; }

/* ---- data tables ------------------------------------------------------ */
DataTable {
    border: round $border; background: $panel; margin-top: 1; height: 1fr;
}
DataTable > .datatable--header {
    background: $panel2; color: $amber; text-style: bold;
}
DataTable > .datatable--odd-row { background: $panel; }
DataTable > .datatable--even-row { background: #131826; }
DataTable > .datatable--cursor {
    background: #1c3a4a; color: $fog; text-style: bold;
}
DataTable > .datatable--hover { background: #182238; }
#recent-sessions { height: 12; }

/* ---- tabs ------------------------------------------------------------- */
TabbedContent { height: auto; }
Tabs { background: $panel; height: 2; }
Tabs > Tab {
    padding: 0 2; color: $dim; background: $panel;
    border-bottom: tall $border;
}
Tabs > Tab.-active { color: $amber; text-style: bold; background: $panel2; }
Tabs > .underline--bar { color: $amber; }

/* ---- dashboard ------------------------------------------------------- */
#dash-panels { height: auto; }
#dash-panels .panel { width: 1fr; }
#dash-panels .panel > .panel-title { color: $cyan; text-style: bold; }
DashboardScreen #output { height: 15%; }  /* keep the sessions table above the fold */
#dash-actions { height: auto; margin: 1 0; }
#dash-actions Button, #dash-nav Button { margin: 0 1 1 0; }
#dash-nav { height: auto; margin: 0 0 1 0; }

/* ---- json console split ---------------------------------------------- */
#split { height: 55%; }
#out-col { width: 1fr; margin: 0 1 0 0; }
#err-col { width: 1fr; }
#out-col Label, #err-col Label { color: $amber; text-style: bold; margin: 0 0 0 1; }
#out-log, #err-log { border: round $border; background: $panel; height: 1fr; }

/* ---- transcript viewer ---------------------------------------------- */
#doc-split { height: 1fr; }
#files-list { width: 36; border: round $border; background: $panel; }
#doc-scroll { width: 1fr; }
#doc-view { width: 1fr; }

/* ---- run screens (chat / debate / community / teams) ------------------ */
#chat { border: round $border; background: $panel; margin: 0 1 1 1; height: 1fr; }
.run-pane { border: round $border; background: $panel; margin-top: 1; height: 1fr; }
#chat-status { height: 1; color: $dim; padding: 0 1; }
#chat-status.busy { color: $amber; }
#chat-status.ready { color: $dim; }
.chat-toolbar { height: auto; margin: 0 0 1 0; }
.chat-toolbar Input { width: 1fr; }
.chat-toolbar .narrow { width: 10; }
#chat-model-list { border: round $border; background: $panel2; }

/* verdict / synthesis / deliverable result panels */
.verdict-panel {
    border: round $border; background: $panel; padding: 0 1;
    height: auto; margin-top: 1; color: $fog;
}
.verdict-panel.win { border: round $green; }
.verdict-panel.loss { border: round $red; }
.verdict-panel.tie { border: round $amber; }
.synthesis-panel {
    border: round #2c4a6e; background: #101827; padding: 0 1;
    height: auto; margin-top: 1; color: $fog;
}
.result-labels { height: auto; margin: 0 0 0 0; color: $dim; }
.consensus { color: $green; }
.dissent { color: $amber; }
.openq { color: $cyan; }
.mini-table { height: 7; }
#community-participants { height: 7; }
#plan-teams { height: 8; }
.plan-meta { color: $dim; margin: 0 0 1 0; }

/* ---- brain tabs ------------------------------------------------------ */
#brain-tabs { height: 1fr; }
#audit-tail { height: 8; border: round $border; background: $panel; margin-top: 1; }
#bench-bars { border: round $border; background: $panel; height: auto; margin-top: 1; padding: 0 1; }

/* brain screen: inline data tables + panels ---------------------------- */
BrainScreen #output { height: 20%; }
BrainScreen DataTable { height: 12; }
BrainScreen .mini-table { height: 6; }
BrainScreen #evo-history { height: 8; }
BrainScreen .form-row Checkbox { margin: 0 1 0 1; }
#evo-genome-row { height: 8; }
#evo-genome-row DataTable { width: 1fr; height: 6; margin-top: 0; }
BrainScreen .form-row Label { width: auto; }
BrainScreen .form-row Input { width: 1fr; }
BrainScreen .form-row Input.narrow { width: 8; }
.status-panel {
    border: round $border; background: $panel; padding: 0 1;
    height: auto; margin-top: 1; color: $fog;
}
.status-panel .kv-key { color: $amber; }
#evolve-stats {
    border: round $border; background: $panel; padding: 0 1;
    height: auto; margin-top: 1; color: $fog;
}
#evolve-pending { height: auto; margin: 1 0 0 0; color: $amber; }
#evolve-diff {
    border: round $border; background: $panel; padding: 0 1;
    height: auto; margin-top: 1; color: $green;
}
#srch-hint { color: $dim; margin: 0 0 0 1; }
#strip-brain { color: $cyan; }

/* brain detail modals --------------------------------------------------- */
#detail-dialog {
    width: 100; height: auto; max-height: 86%;
    border: heavy $border2; background: $panel; padding: 1 2;
}
#detail-dialog .section-label { margin: 1 0 0 0; }
#detail-dialog Button { margin: 1 1 0 0; }
#detail-log { height: 20; border: round $border; background: $panel2; margin-top: 1; }

/* ---- help / confirm modals -------------------------------------------- */
HelpModal, ConfirmModal, BrainDetailModal { align: center middle; }
#help-dialog, #confirm-dialog {
    width: 84; height: auto; max-height: 80%;
    border: heavy $border2; background: $panel; padding: 1 2;
}
#help-dialog .section-label { margin: 1 0 0 0; }
#confirm-dialog Button { margin: 1 1 0 0; }
.key-chip { color: $cyan; text-style: bold; }
"""
