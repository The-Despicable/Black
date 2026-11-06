"""Mission-control theme for the raphael-ma TUI.

Near-black background, amber + cyan accents, boxed panels, monospace feel.
All colors are declared here so the whole console can be re-skinned in one
place.
"""

from __future__ import annotations

PALETTE = {
    "bg": "#0b0e14",
    "panel": "#11151f",
    "panel2": "#161b27",
    "border": "#2a3242",
    "border2": "#3a4356",
    "amber": "#ffb454",
    "cyan": "#39bae6",
    "red": "#e05661",
    "green": "#3fd084",
    "dim": "#8b93a7",
    "fog": "#d5dbe6",
}

MISSION_CONTROL_CSS = """
$bg: #0b0e14;
$panel: #11151f;
$panel2: #161b27;
$border: #2a3242;
$border2: #3a4356;
$amber: #ffb454;
$cyan: #39bae6;
$red: #e05661;
$green: #3fd084;
$dim: #8b93a7;
$fog: #d5dbe6;

Screen {
    background: $bg;
    color: $fog;
}

/* ---- status strip --------------------------------------------------- */
#strip { height: 1; background: $panel; }
.strip-item { width: auto; color: $dim; background: $panel; padding: 0 1; }
#strip-busy { color: $amber; }

.badge { width: auto; padding: 0 2; background: $panel2; color: $dim; text-style: bold; }
.badge.mock { color: $cyan; }
.badge.live { color: $red; background: #2a1216; }
.badge.warn { color: $amber; }
.badge.ok { color: $green; }
.badge.danger { color: $red; background: #2a1216; }

/* ---- chrome ---------------------------------------------------------- */
#body { height: 1fr; padding: 0 1; }
#cmdbar { height: 1; color: $cyan; background: $panel2; padding: 0 1; }
#output { height: 34%; border: round $border; background: $panel; margin-top: 1; }
#result { height: 2; padding: 0 1; }
.result.run { color: $amber; }
.result.ok { color: $green; }
.result.fail { color: $red; }

/* ---- panels ---------------------------------------------------------- */
.panel { border: round $border; background: $panel; padding: 0 1; margin: 0 1 1 0; height: auto; }
.panel.danger { border: heavy $red; background: #2a1216; color: $fog; }
.section-label { color: $amber; text-style: bold; margin: 1 0 0 0; }

/* ---- forms ----------------------------------------------------------- */
.form-row { height: auto; margin: 0 0 1 0; }
.form-row Label { width: auto; padding: 1 1 0 0; color: $dim; }
.form-row Input { width: 1fr; }
.form-row Select { width: 26; }
.form-row Checkbox { width: auto; margin: 1 1 0 1; }
.field-label { width: 14; color: $dim; padding: 1 1 0 0; }

Button { background: $panel2; color: $amber; border: round $border; margin: 0 1 0 0; }
Button:hover { background: #1d2433; }
Button:focus { text-style: bold; border: tall $amber; }
Button.danger { color: $red; border: round #4a2027; }

Input { background: $panel2; border: round $border; }
Input:focus { border: tall $amber; }
Select { background: $panel2; border: round $border; }
Select:focus { border: tall $amber; }
Checkbox { background: $panel; }

DataTable { border: round $border; background: $panel; margin-top: 1; height: 1fr; }
#recent-sessions { height: 12; }

/* ---- dashboard ------------------------------------------------------- */
#dash-panels { height: auto; }
#dash-panels .panel { width: 1fr; }
#dash-actions { height: auto; margin: 1 0; }
#dash-actions Button { margin: 0 1 1 0; }

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

/* ---- brain tabs ------------------------------------------------------ */
TabbedContent { height: auto; }
#brain-tabs { height: auto; }
#audit-tail { height: 8; border: round $border; background: $panel; margin-top: 1; }
#bench-bars { border: round $border; background: $panel; height: auto; margin-top: 1; padding: 0 1; }

/* ---- help modal ------------------------------------------------------ */
HelpModal, ConfirmModal { align: center middle; }
#help-dialog, #confirm-dialog {
    width: 84; height: auto; max-height: 80%;
    border: heavy $border2; background: $panel; padding: 1 2;
}
#help-dialog .section-label { margin: 1 0 0 0; }
#confirm-dialog Button { margin: 1 1 0 0; }
"""
