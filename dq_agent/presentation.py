"""Lumen Row's local visual identity, separate from workflow and data logic.

Hero artwork is supplied as original local PNG assets, icons are vector SVG,
fonts are system fonts, and dynamic text is escaped. No remote assets or
JavaScript are loaded by these components.
Native Streamlit controls remain responsible for every user action.
"""

from __future__ import annotations

from base64 import b64encode
from html import escape
from pathlib import Path

import streamlit as st


BRAND_NAME = "Lumen Row"
BRAND_TAGLINE = "Data quality. Made clear."


def _svg_image(svg: str, *, alt: str = "", color: str = "#52774b") -> str:
    """Embed static SVG as an image: Streamlit sanitizes inline SVG elements.

    Images cannot inherit a page's currentColor, so resolve it explicitly before
    encoding. Every SVG originates in this module; no user content enters it.
    """
    if 'xmlns="http://www.w3.org/2000/svg"' not in svg:
        svg = svg.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
    encoded = b64encode(svg.replace("currentColor", color).encode("utf-8")).decode("ascii")
    decorative = ' aria-hidden="true"' if not alt else ""
    return f'<img src="data:image/svg+xml;base64,{encoded}" alt="{escape(alt, quote=True)}"{decorative} draggable="false"/>'


_CSS = r"""
<style>
:root {
  --cw-paper: #f7f7ef;
  --cw-white: #ffffff;
  --cw-ink: #19382f;
  --cw-muted: #647168;
  --cw-forest: #183d32;
  --cw-deep: #122f28;
  --cw-teal: #286958;
  --cw-lime: #deeea8;
  --cw-line: #dce2d5;
  --cw-soft: #edf1e6;
  --cw-amber: #99652d;
  --cw-focus: #a77524;
}
html, body, .stApp {
  font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Arial, sans-serif;
  color: var(--cw-ink);
}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
  background: var(--cw-paper);
}
[data-testid="stHeader"] {background: rgba(247,247,239,.95);}
[data-testid="stMainBlockContainer"] {
  max-width: 1400px;
  padding: 2.1rem 3.7rem 4rem;
}
[data-testid="stMain"] [data-testid="stVerticalBlock"] {gap: 1.05rem;}
[data-testid="stMain"] h2 {
  color: var(--cw-ink); font-size: 1.65rem; font-weight: 620;
  letter-spacing: -.045em; padding-top: .25rem;
}
[data-testid="stMain"] h3 {
  color: var(--cw-ink); font-size: 1.24rem; font-weight: 620;
  letter-spacing: -.025em;
}
[data-testid="stMarkdownContainer"] p {line-height: 1.65;}
[data-testid="stCaptionContainer"] {color: var(--cw-muted); font-size: .81rem; line-height: 1.55;}
[data-testid="stMain"] [data-testid="stWidgetLabel"] p {font-weight: 600; color: #304b3e; font-size: .87rem;}
[data-testid="stSidebar"] {
  background: var(--cw-deep); border-right: 0;
  color: #edf1e4;
}
[data-testid="stSidebarContent"] {padding: 1.3rem .65rem 1.8rem;}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {color: #f3f5ea; letter-spacing: -.025em;}
[data-testid="stSidebar"] h2 {font-size: 1.13rem;}
[data-testid="stSidebar"] h3 {font-size: .95rem;}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {color: #d8e1d8; font-size: .83rem;}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {color: #b4c6b8;}
[data-testid="stSidebar"] button [data-testid="stMarkdownContainer"] p {color: inherit;}
[data-testid="stSidebar"] hr {border-color: #355246; margin: 1.5rem 0;}
[data-testid="stSidebar"] [data-baseweb="select"] > div,
[data-testid="stSidebar"] [data-baseweb="input"],
[data-testid="stSidebar"] [data-baseweb="base-input"] {
  background: #224338; color: #f2f5e9; border-color: #52705f; border-radius: 8px;
}
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] [role="combobox"] {color: #f2f5e9;}
[data-testid="stSidebar"] input::placeholder {color: #afc3b5;}
[data-testid="stSidebar"] [data-baseweb="select"] svg {fill: #d1dfd1;}
[data-testid="stSidebar"] [data-testid="stExpander"] {
  border-color: #3d594a; background: transparent; color: #eff3e6;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary p {color: #e2e9db;}
[data-testid="stSidebar"] [data-testid="stExpander"] summary svg {color: #d3e1d3;}
[data-testid="stSidebar"] [data-testid="stForm"] {border-color: #3d594a; padding: .8rem;}
[data-testid="stSidebar"] button[kind="secondary"],
[data-testid="stSidebar"] button[kind="secondaryFormSubmit"] {
  background: transparent; color: #edf3e4; border-color: #668471;
}
[data-testid="stSidebar"] button[kind="secondary"]:hover,
[data-testid="stSidebar"] button[kind="secondaryFormSubmit"]:hover {
  background: #294b3e; border-color: #a0bc9b; color: #fff;
}
[data-testid="stSidebar"] button[kind="primary"] {
  background: var(--cw-lime); color: #183b2e; border-color: var(--cw-lime);
}
[data-testid="stSidebar"] button[kind="primary"]:hover {
  background: #ebf7c5; border-color: #ebf7c5; color: #122e24;
}
[data-testid="stSidebarCollapseButton"] button {color: #dfeadc;}
[data-testid="stSidebar"] button[aria-label="Collapse sidebar"] {visibility: visible !important;}
[data-testid="stSidebarCollapsedControl"] button {color: var(--cw-forest);}
button[kind="primary"], button[kind="primaryFormSubmit"] {
  background: var(--cw-forest); border: 1px solid var(--cw-forest);
  color: white; border-radius: 9px; min-height: 44px; font-weight: 600;
  padding: .58rem 1.15rem; box-shadow: none;
}
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover {
  background: #285d49; border-color: #285d49; color: white;
}
button[kind="secondary"], button[kind="secondaryFormSubmit"],
[data-testid="stDownloadButton"] button {
  background: #fff; border: 1px solid #b9c6b4; color: var(--cw-forest);
  border-radius: 9px; min-height: 42px; font-weight: 550; padding: .5rem .95rem;
}
button[kind="secondary"]:hover, button[kind="secondaryFormSubmit"]:hover,
[data-testid="stDownloadButton"] button:hover {
  color: var(--cw-forest); background: #edf3e3; border-color: #6d8e73;
}
button:disabled, button:disabled:hover,
[data-testid="stSidebar"] button:disabled,
[data-testid="stSidebar"] button:disabled:hover {
  background: #e6eadf; color: #737e70; border-color: #d1d9ca; cursor: not-allowed;
}
button:focus-visible, a:focus-visible, summary:focus-visible,
input:focus-visible, textarea:focus-visible, [role="tab"]:focus-visible {
  outline: 3px solid var(--cw-focus) !important; outline-offset: 3px;
}
[data-testid="stMain"] [data-baseweb="input"],
[data-testid="stMain"] [data-baseweb="select"] > div,
[data-testid="stMain"] [data-baseweb="textarea"] {
  background: #fff; border: 1px solid #bdc9b6; border-radius: 8px;
}
[data-testid="stMain"] input, [data-testid="stMain"] textarea {color: #1d3b2f;}
[data-testid="stMain"] input::placeholder, [data-testid="stMain"] textarea::placeholder {color: #697969;}
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stMain"] [data-testid="stForm"] {
  border-color: var(--cw-line); border-radius: 16px; background: #fff;
}
[data-testid="stMain"] [data-testid="stExpander"] {
  border-color: #d3ddcb; border-radius: 10px; background: #fafbf5;
}
[data-testid="stMain"] [data-testid="stExpander"] summary {padding-top: .7rem; padding-bottom: .7rem;}
[data-testid="stFileUploaderDropzone"] {
  background: #f2f5eb; border: 1px dashed #9caf90; border-radius: 12px;
  padding: 1.25rem; min-height: 112px;
}
[data-testid="stFileUploaderDropzone"] svg {color: #567e5c;}
[data-testid="stDataFrame"] {border: 1px solid #d1dccb; border-radius: 10px; overflow: hidden;}
[data-testid="stMetric"] {background: #eef3e6; border-radius: 12px; padding: 1rem 1.2rem;}
[data-testid="stMetricValue"] {color: var(--cw-forest); font-size: 2.3rem; letter-spacing: -.05em;}
[data-testid="stMetricLabel"] {color: #52654f;}
[data-testid="stAlert"] {border-radius: 10px; border: 1px solid #d5dfca;}
[data-baseweb="tab-list"] {gap: 1.5rem; border-bottom: 1px solid #d4ddce;}
[data-baseweb="tab"] {color: #627260; padding: .85rem .15rem; font-weight: 550;}
[data-baseweb="tab"][aria-selected="true"] {color: var(--cw-forest); font-weight: 700;}
[data-baseweb="tab-highlight"] {background: var(--cw-forest); height: 3px;}
[data-baseweb="radio"] {accent-color: var(--cw-forest);}
hr {border-color: var(--cw-line);}

/* Brand and the small editorial components below never contain controls. */
.cw-brand {display: flex; align-items: center; gap: 11px; color: var(--cw-forest);}
.cw-brand img {width: 37px; height: 37px; flex-shrink: 0;}
.cw-brand-name {font-size: 27px; font-weight: 650; letter-spacing: -.065em; line-height: 1.05;}
.cw-brand-byline {font-size: 10px; letter-spacing: .13em; text-transform: uppercase; margin-top: 6px; opacity: .7;}
.cw-brand--compact {color: #f0f4df; margin: .35rem 0 1.8rem;}
.cw-brand--compact .cw-brand-name {font-size: 29px;}
.cw-brand--compact .cw-brand-byline {color: #c6d8b9; opacity: 1;}
.cw-topline {display: flex; align-items: center; justify-content: space-between; gap: 15px; margin: .3rem 0 1.8rem;}
.cw-topline-label {color: #5e705e; font-size: 10px; text-transform: uppercase; font-weight: 700; letter-spacing: .19em;}
.cw-workspace-tag {display: inline-flex; align-items: center; gap: 7px; color: #61715d; font-size: 11px;}
.cw-workspace-dot {width: 6px; height: 6px; border-radius: 50%; background: #507e4f;}
.cw-hero {display: grid; grid-template-columns: 1.02fr 1fr; align-items: center; gap: 2.3rem; margin: 0 0 1.6rem;}
.cw-eyebrow {font-size: 10px; font-weight: 700; letter-spacing: .17em; text-transform: uppercase; color: #55764f; margin: 0 0 1rem;}
.cw-hero h1 {font-size: clamp(43px,4.1vw,67px); line-height: 1.04; letter-spacing: -.065em; font-weight: 580; color: var(--cw-ink); margin: 0 0 1.35rem; padding: 0;}
.cw-hero h1 em {font-family: Georgia, "Times New Roman", serif; color: #397858; font-weight: 400; letter-spacing: -.065em;}
.cw-hero-description {color: #62715e; font-size: 15px; line-height: 1.75; max-width: 355px; margin: 0 0 1.8rem;}
.cw-hero-note {display: flex; gap: 9px; align-items: center; color: #405c41; font-size: 11px; font-weight: 550;}
.cw-hero-note img {width: 17px; height: 17px; flex-shrink: 0;}
.cw-art {margin: 0; position: relative; background: #e9eee0; border-radius: 22px; overflow: hidden; border: 1px solid #dfe7d6;}
.cw-art img {display: block; width: 100%; height: auto; object-fit: contain;}
.cw-art figcaption {font-size: 10px; font-weight: 550; color: #5a6e54; letter-spacing: .025em; padding: 0 22px 17px;}
.cw-assurances {display: flex; gap: 27px; flex-wrap: wrap; padding: 1.1rem 0 1.35rem; margin-bottom: 1.1rem; border-bottom: 1px solid var(--cw-line);}
.cw-assurance {display: flex; align-items: center; gap: 8px; color: #52654c; font-size: 11px;}
.cw-assurance img {width: 16px; height: 16px;}
.cw-section-intro {display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; margin: .4rem 0 .15rem;}
.cw-section-intro h2 {margin: 0; padding: 0; font-size: 25px; font-weight: 600; letter-spacing: -.045em; color: var(--cw-ink);}
.cw-section-intro p {margin: 6px 0 0; color: #65755e; font-size: 12px;}
.cw-section-number {font-size: 11px; font-weight: 600; color: #77876c; letter-spacing: .08em; padding-bottom: 4px; white-space: nowrap;}
.cw-job-header {margin: .3rem 0 .6rem;}
.cw-breadcrumb {display: flex; align-items: center; gap: 9px; font-size: 10px; font-weight: 650; letter-spacing: .16em; text-transform: uppercase; color: #68805d; margin-bottom: 1.2rem;}
.cw-job-mark {display: inline-flex; color: #55784c;}
.cw-job-mark img {width: 23px; height: 23px;}
.cw-job-title-row {display: flex; justify-content: space-between; align-items: center; gap: 20px;}
.cw-job-header h1 {margin: 0; padding: 0; font-size: clamp(29px,3vw,43px); font-weight: 600; letter-spacing: -.055em; line-height: 1.15; color: var(--cw-ink); overflow-wrap: anywhere;}
.cw-job-header p {margin: .7rem 0 0; font-size: 12px; color: #60745a;}
.cw-status {display: inline-flex; gap: 8px; align-items: center; border-radius: 100px; padding: 8px 12px; font-size: 11px; line-height: 1.3; font-weight: 600; color: #335b35; background: #e7efd9; border: 1px solid #c8dab8; flex-shrink: 0; max-width: 265px;}
.cw-status-dot {height: 6px; width: 6px; border-radius: 50%; background: #548153; flex-shrink: 0;}
.cw-progress {display: grid; grid-template-columns: repeat(5,1fr); list-style: none; padding: 0; margin: 1.3rem 0 1.65rem;}
.cw-progress li {position: relative; margin: 0; padding: 0 9px 0 0; display: flex; gap: 9px; align-items: center; font-size: 11px; color: #788271;}
.cw-progress li::after {content: ""; flex: 1; height: 1px; background: #d8e1cc; margin-left: 5px;}
.cw-progress li:last-child::after {display: none;}
.cw-progress-index {display: grid; place-items: center; height: 26px; width: 26px; border-radius: 50%; border: 1px solid #cbd7c2; font-size: 10px; background: #f7f7ef; flex-shrink: 0;}
.cw-progress-index img {width: 13px; height: 13px;}
.cw-progress .cw-step-done {color: #49674a;}
.cw-step-done .cw-progress-index {background: #e1ecd2; border-color: #d0dfbf; color: #416a41;}
.cw-progress .cw-step-active {color: var(--cw-forest); font-weight: 700;}
.cw-step-active .cw-progress-index {background: var(--cw-forest); border-color: var(--cw-forest); color: white;}
.cw-progress-note {font-size: 12px; color: #8b632d; margin: -.6rem 0 1rem;}
.cw-metrics {display: grid; grid-template-columns: repeat(3,1fr); border-top: 1px solid var(--cw-line); border-bottom: 1px solid var(--cw-line); padding: 1.25rem 0; margin: .3rem 0 1.1rem;}
.cw-metric {padding: 0 1.7rem; border-left: 1px solid var(--cw-line);}
.cw-metric:first-child {border-left: 0; padding-left: 0;}
.cw-metric-label {font-size: 10px; font-weight: 650; letter-spacing: .13em; text-transform: uppercase; color: #6d7e63;}
.cw-metric-value {font-size: 43px; font-weight: 500; line-height: 1.2; letter-spacing: -.06em; color: var(--cw-forest); margin: 4px 0 2px; font-variant-numeric: tabular-nums;}
.cw-metric-value--attention {color: #96652e;}
.cw-metric-caption {font-size: 11px; color: #718067;}
@media (min-width:1600px) {
  [data-testid="stMainBlockContainer"] {padding-left: 4.4rem; padding-right: 4.4rem;}
}
@media (max-width:1100px) {
  [data-testid="stMainBlockContainer"] {padding-left: 2rem; padding-right: 2rem;}
  .cw-hero {gap: 1.4rem;}
  .cw-hero h1 {font-size: 46px;}
  .cw-hero-description {font-size: 13px;}
  .cw-assurances {gap: 16px;}
}
@media (max-width:800px) {
  [data-testid="stMainBlockContainer"] {padding: 1.6rem 1.15rem 3rem;}
  .cw-hero {grid-template-columns: 1fr; gap: 1.5rem;}
  .cw-hero h1 {font-size: clamp(43px,7.5vw,62px);}
  .cw-hero-description {max-width: 470px; font-size: 14px; margin-bottom: 1.1rem;}
  .cw-art {max-width: 550px;}
  .cw-art img {max-height: 355px;}
  .cw-topline {margin-bottom: 1.5rem;}
  .cw-job-title-row {align-items: flex-start; flex-direction: column; gap: 12px;}
  .cw-progress li {flex-direction: column; align-items: flex-start; gap: 7px; font-size: 10px;}
  .cw-progress li::after {position: absolute; top: 13px; left: 29px; width: calc(100% - 37px); margin: 0;}
  .cw-metric {padding: 0 .8rem;}
  .cw-metric-value {font-size: 35px;}
  .cw-metric-label {font-size: 9px; letter-spacing: .08em;}
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {scroll-behavior: auto !important; transition: none !important; animation: none !important;}
}
</style>
"""

_PALETTES = {
    "dark": {
        "paper": "#151326", "panel": "#24223d", "panel2": "#302b4b",
        "ink": "#f4f0ff", "muted": "#c1b7d7", "faint": "#a89dbe",
        "line": "#50486d", "line-soft": "#37304f", "primary": "#beabff",
        "primary-ink": "#24164b", "accent": "#cab9ff", "accent2": "#f3bd79",
        "sidebar": "#100f20", "input": "#241f3b", "attention": "#f3c57c",
        "grid": "#40345d", "glow": "#b293ff", "beam": "#dcc5ff",
        "scene-panel": "#302442", "scene-label": "#c6b5e0",
        "hero-shade": "rgba(21,19,38,.96)", "hero-middle": "rgba(21,19,38,.72)",
        "motion-raw": "#f4c18d", "motion-lilac": "#d7baff", "motion-clean": "#a3f1cf",
        "motion-glass": "rgba(51,34,78,.48)", "motion-glow": "rgba(212,173,255,.54)",
    },
    "light": {
        "paper": "#f7f4f3", "panel": "#fffdfb", "panel2": "#f0eafb",
        "ink": "#292341", "muted": "#655c76", "faint": "#756982",
        "line": "#d7cfe4", "line-soft": "#e5deea", "primary": "#5741d6",
        "primary-ink": "#ffffff", "accent": "#6950c6", "accent2": "#956926",
        "sidebar": "#f0ebf5", "input": "#ffffff", "attention": "#8d5c0f",
        "grid": "#d0c0e7", "glow": "#9862da", "beam": "#ad8be8",
        "scene-panel": "#e3d8f3", "scene-label": "#756382",
        "hero-shade": "rgba(250,246,241,.97)", "hero-middle": "rgba(250,246,241,.72)",
        "motion-raw": "#a96424", "motion-lilac": "#8551bf", "motion-clean": "#168366",
        "motion-glass": "rgba(255,251,255,.48)", "motion-glow": "rgba(172,120,238,.40)",
    },
}

_THEME_CSS = r"""
<style>
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {background:var(--cw-paper);color:var(--cw-ink);}
[data-testid="stHeader"] {background:var(--cw-paper);}
[data-testid="stHeader"] button,[data-testid="stToolbar"] button {color:var(--cw-ink);}
[data-testid="stSidebarCollapsedControl"],button[aria-label="Expand sidebar"] {visibility:visible!important;opacity:1!important;}
[data-testid="stCaptionContainer"] {opacity:1;}
#cw-start {scroll-margin-top:5rem;}
[data-testid="stMainBlockContainer"] {max-width:1500px;padding:4.6rem 3.5rem 4.5rem;}
[data-testid="stMain"] h1,[data-testid="stMain"] h2,[data-testid="stMain"] h3 {color:var(--cw-ink);}
[data-testid="stMain"] [data-testid="stMarkdownContainer"] p {color:var(--cw-ink);}
[data-testid="stMain"] [data-testid="stCaptionContainer"],
[data-testid="stMain"] [data-testid="stCaptionContainer"] p {color:var(--cw-muted);}
[data-testid="stMain"] [data-testid="stWidgetLabel"] p {color:var(--cw-ink);font-size:.88rem;}
[data-testid="stSidebar"] {background:var(--cw-sidebar);border-right:1px solid var(--cw-line-soft);color:var(--cw-ink);}
[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {color:var(--cw-ink);}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {color:var(--cw-muted);}
[data-testid="stSidebar"] [data-testid="stExpander"] summary p,
[data-testid="stSidebar"] [data-testid="stExpander"] summary svg {color:var(--cw-ink);}
[data-testid="stSidebar"] hr {border-color:var(--cw-line);}
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stMain"] [data-testid="stForm"],
[data-testid="stSidebar"] [data-testid="stForm"] {background:var(--cw-panel);border-color:var(--cw-line);border-radius:16px;}
[data-testid="stMain"] [data-testid="stExpander"],
[data-testid="stSidebar"] [data-testid="stExpander"] {background:var(--cw-panel);border-color:var(--cw-line);color:var(--cw-ink);}
[data-testid="stMain"] [data-baseweb="input"],
[data-testid="stMain"] [data-baseweb="base-input"],
[data-testid="stMain"] [data-baseweb="select"] > div,
[data-testid="stMain"] [data-baseweb="textarea"],
[data-testid="stSidebar"] [data-baseweb="input"],
[data-testid="stSidebar"] [data-baseweb="base-input"],
[data-testid="stSidebar"] [data-baseweb="select"] > div {background:var(--cw-input);border-color:var(--cw-line);color:var(--cw-ink);}
[data-testid="stMain"] input,[data-testid="stMain"] textarea,
[data-testid="stSidebar"] input,[data-testid="stSidebar"] textarea {color:var(--cw-ink);-webkit-text-fill-color:var(--cw-ink);}
[data-testid="stMain"] input::placeholder,[data-testid="stMain"] textarea::placeholder,
[data-testid="stSidebar"] input::placeholder {color:var(--cw-faint);-webkit-text-fill-color:var(--cw-faint);}
[data-baseweb="select"] [role="combobox"],
[data-baseweb="select"] span,[data-baseweb="select"] [data-testid="stMarkdownContainer"] {color:var(--cw-ink);}
[data-testid="stSidebar"] [data-baseweb="select"] svg,[data-baseweb="select"] svg {fill:var(--cw-muted);}
[data-baseweb="popover"] [role="listbox"],
[data-baseweb="popover"] [role="option"] {background:var(--cw-panel);color:var(--cw-ink);}
[data-baseweb="popover"] [role="option"][aria-selected="true"] {background:var(--cw-panel2);color:var(--cw-ink);}
[data-testid="stMain"] button [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] button [data-testid="stMarkdownContainer"] p {color:inherit;}
button[kind="primary"],button[kind="primaryFormSubmit"],
[data-testid="stSidebar"] button[kind="primary"] {
  background:var(--cw-primary);border-color:var(--cw-primary);color:var(--cw-primary-ink);
  min-height:46px;border-radius:9px;font-weight:650;box-shadow:0 4px 24px #00000016;
}
button[kind="primary"]:hover,button[kind="primaryFormSubmit"]:hover,
[data-testid="stSidebar"] button[kind="primary"]:hover {
  background:var(--cw-primary);border-color:var(--cw-accent);color:var(--cw-primary-ink);filter:brightness(1.08);
}
button[kind="secondary"],button[kind="secondaryFormSubmit"],
[data-testid="stDownloadButton"] button,
[data-testid="stSidebar"] button[kind="secondary"],
[data-testid="stSidebar"] button[kind="secondaryFormSubmit"] {background:var(--cw-panel);border-color:var(--cw-line);color:var(--cw-ink);}
button[kind="secondary"]:hover,button[kind="secondaryFormSubmit"]:hover,
[data-testid="stDownloadButton"] button:hover,
[data-testid="stSidebar"] button[kind="secondary"]:hover,
[data-testid="stSidebar"] button[kind="secondaryFormSubmit"]:hover {background:var(--cw-panel2);border-color:var(--cw-accent);color:var(--cw-ink);}
button:disabled,button:disabled:hover,[data-testid="stSidebar"] button:disabled,
[data-testid="stSidebar"] button:disabled:hover {background:var(--cw-panel2);border-color:var(--cw-line);color:var(--cw-faint);filter:none;box-shadow:none;}
[data-testid="stButton"] button:disabled {
  background:var(--cw-panel2)!important;border-color:var(--cw-line)!important;color:var(--cw-muted)!important;
}
[data-testid="stButton"] button:disabled [data-testid="stMarkdownContainer"] p {color:inherit!important;}
[data-testid="stButtonGroup"] button {background:var(--cw-panel);border:1px solid var(--cw-line);color:var(--cw-ink);border-radius:8px;}
[data-testid="stButtonGroup"] button[aria-pressed="true"],
[data-testid="stButtonGroup"] button[kind="segmented_controlActive"] {background:var(--cw-primary);border-color:var(--cw-primary);color:var(--cw-primary-ink);}
/* Streamlit 1.66 uses React Aria for these controls. Target its semantic
   groups and documented test IDs as well as the older BaseWeb wrappers. */
[data-testid="stSelectbox"] .react-aria-ComboBox > [role="group"],
[data-testid="stSelectbox"] [role="group"]:has(input[role="combobox"]),
[data-testid="stTextInputRootElement"],
[data-testid="stTextAreaRootElement"] {
  background-color:var(--cw-input)!important;
  color:var(--cw-ink)!important;
  border-color:var(--cw-line)!important;
  border-radius:8px;
}
[data-testid="stSelectbox"] input[role="combobox"],
input[data-testid="stTextInputField"],
[data-testid="stTextAreaRootElement"] textarea {
  background-color:transparent!important;
  color:var(--cw-ink)!important;
  -webkit-text-fill-color:var(--cw-ink)!important;
  caret-color:var(--cw-accent);
}
[data-testid="stSelectbox"] input[role="combobox"]::placeholder,
input[data-testid="stTextInputField"]::placeholder,
[data-testid="stTextAreaRootElement"] textarea::placeholder {
  color:var(--cw-faint)!important;-webkit-text-fill-color:var(--cw-faint)!important;opacity:1;
}
[data-testid="stSelectbox"] button[aria-label="Open"],
[data-testid="stSelectbox"] button[aria-label="Clear value"],
[data-testid="stTextInputRootElement"] button {
  color:var(--cw-muted)!important;background:transparent!important;border-color:transparent!important;
}
[data-testid="stSelectbox"] button svg,
[data-testid="stTextInputRootElement"] button svg {color:var(--cw-muted);fill:currentColor;}
[data-testid="stSelectbox"] [role="group"]:focus-within,
[data-testid="stTextInputRootElement"]:focus-within,
[data-testid="stTextAreaRootElement"]:focus-within {border-color:var(--cw-accent)!important;}
/* Plain values and the calendar are separate React Aria surfaces. Keep them
   readable when the app appearance differs from Streamlit's base theme. */
[data-testid="stText"], [data-testid="stText"] span {
  color:var(--cw-ink)!important;-webkit-text-fill-color:var(--cw-ink)!important;
}
[data-testid="stDateInputField"] {
  background:var(--cw-input)!important;color:var(--cw-ink)!important;
  border-color:var(--cw-line)!important;
}
[data-testid="stDateInputField"] [data-type] {
  color:var(--cw-ink)!important;-webkit-text-fill-color:var(--cw-ink)!important;
}
[data-testid="stDateInputField"] [data-placeholder] {
  color:var(--cw-faint)!important;-webkit-text-fill-color:var(--cw-faint)!important;
}
[data-testid="stDateInputCalendarButton"] {
  color:var(--cw-muted)!important;background:transparent!important;
}
[data-testid="stDateInputField"]:focus-within {border-color:var(--cw-accent)!important;}
[data-testid="stDateInputCalendar"], [data-testid="stDateInputCalendar"] [role="application"] {
  background:var(--cw-panel)!important;color:var(--cw-ink)!important;border-color:var(--cw-line)!important;
}
[data-testid="stDateInputCalendar"] button,
[data-testid="stDateInputCalendar"] [role="button"],
[data-testid="stDateInputCalendar"] th {
  color:var(--cw-ink)!important;background:transparent!important;
}
[data-testid="stDateInputCalendar"] [role="button"][data-hovered],
[data-testid="stDateInputCalendar"] button:hover {background:var(--cw-panel2)!important;}
[data-testid="stDateInputCalendar"] [role="button"][data-selected] {
  color:var(--cw-primary-ink)!important;background:var(--cw-primary)!important;
}
[data-testid="stDateInputCalendar"] [role="button"][aria-disabled="true"] {
  color:var(--cw-faint)!important;
}
[data-testid="stSelectboxVirtualDropdown"],
[data-testid="stSelectboxVirtualDropdown"] [role="listbox"],
.react-aria-Popover [role="listbox"],
.react-aria-ListBox {
  background-color:var(--cw-panel)!important;color:var(--cw-ink)!important;border-color:var(--cw-line)!important;
}
[data-testid="stSelectboxVirtualDropdown"] [role="option"],
.react-aria-ListBox [role="option"] {
  color:var(--cw-ink)!important;background-color:var(--cw-panel)!important;
}
[data-testid="stSelectboxVirtualDropdown"] [role="option"][aria-selected="true"],
[data-testid="stSelectboxVirtualDropdown"] [role="option"][data-selected],
[data-testid="stSelectboxVirtualDropdown"] [role="option"][data-focused],
[data-testid="stSelectboxVirtualDropdown"] [role="option"][data-hovered],
.react-aria-ListBox [role="option"][aria-selected="true"] {
  background-color:var(--cw-panel2)!important;color:var(--cw-ink)!important;
}
[data-testid="stSelectboxVirtualDropdown"] [role="option"] * {color:inherit;}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"] {
  color:var(--cw-ink)!important;background-color:var(--cw-panel)!important;
  border-color:var(--cw-line)!important;
}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"][role="radio"][aria-checked="true"],
[data-testid="stButtonGroup"] button[data-variant="segmented_control"][data-selected] {
  background-color:var(--cw-primary)!important;color:var(--cw-primary-ink)!important;
  border-color:var(--cw-primary)!important;
}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"] [data-testid="stMarkdownContainer"] p {color:inherit!important;}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"][data-disabled],
[data-testid="stSelectbox"] input[role="combobox"]:disabled,
input[data-testid="stTextInputField"]:disabled,
[data-testid="stTextAreaRootElement"] textarea:disabled {
  color:var(--cw-faint)!important;-webkit-text-fill-color:var(--cw-faint)!important;cursor:not-allowed;
}
[data-testid="stCheckbox"] label > div:not([data-testid]) {
  background-color:var(--cw-input);border-color:var(--cw-faint);
}
[data-testid="stCheckbox"] label[data-selected] > div:not([data-testid]) {
  background-color:var(--cw-primary);border-color:var(--cw-primary);
}
[data-testid="stCheckbox"] label[data-selected] > div:not([data-testid]) svg {
  stroke:var(--cw-primary-ink);color:var(--cw-primary-ink);
}
[data-testid="stRadioOption"] > div > div:not([data-testid]) {
  background-color:var(--cw-input);border-color:var(--cw-faint);
}
[data-testid="stRadioOption"][data-selected] > div > div:not([data-testid]) {
  background-color:var(--cw-primary);border-color:var(--cw-primary);
}
[data-testid="stRadioOption"][data-selected] > div > div:not([data-testid]) > div {background-color:var(--cw-primary-ink);}
[data-testid="stRadioCaption"],[data-testid="stRadioCaption"] p {color:var(--cw-muted)!important;}
[data-testid="stExpander"] details,
[data-testid="stExpander"] summary,
[data-testid="stExpanderDetails"] {background-color:var(--cw-panel);color:var(--cw-ink);border-color:var(--cw-line);}
[data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] p {color:var(--cw-ink)!important;}
[data-testid="stExpander"] summary svg {color:var(--cw-muted);}
[data-testid="stMain"] [data-testid="stCaptionContainer"] p,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {color:var(--cw-muted)!important;}
[data-testid="stFileUploaderDropzone"] {background:var(--cw-panel2);border-color:var(--cw-faint);}
[data-testid="stFileUploaderDropzone"] svg {color:var(--cw-accent);}
[data-testid="stFileUploaderDropzone"] small {color:var(--cw-muted);}
[data-testid="stAlert"] {background:var(--cw-panel2);border-color:var(--cw-line);color:var(--cw-ink);}
[data-testid="stMetric"] {background:var(--cw-panel2);}
[data-testid="stMetricValue"],[data-testid="stMetricLabel"] {color:var(--cw-ink);}
[data-baseweb="tab-list"] {border-color:var(--cw-line);}
[data-baseweb="tab"] {color:var(--cw-muted);}
[data-baseweb="tab"][aria-selected="true"] {color:var(--cw-accent);}
[data-baseweb="tab-highlight"] {background:var(--cw-accent);}
/* Streamlit draws grids to a canvas. Keep its native dark palette intact in
   both modes, as a crisp technical inset, rather than distorting data colors. */
[data-testid="stDataFrame"] {background:#0d1e2b;border:1px solid var(--cw-line);border-radius:11px;box-shadow:0 8px 25px #0000000a;}
[data-testid="stSidebarCollapseButton"] button,
[data-testid="stSidebarCollapsedControl"] button {color:var(--cw-ink);}
hr {border-color:var(--cw-line);}
button:focus-visible,a:focus-visible,summary:focus-visible,
input:focus-visible,textarea:focus-visible,[role="tab"]:focus-visible {outline:3px solid var(--cw-accent)!important;outline-offset:3px;}
.cw-brand {color:var(--cw-ink);gap:12px;}
.cw-brand img {width:40px;height:40px;}
.cw-brand-name {font-size:30px;font-weight:650;letter-spacing:-.06em;}
.cw-brand-byline,.cw-brand--compact .cw-brand-byline {color:var(--cw-muted);opacity:1;letter-spacing:.15em;font-size:8px;}
.cw-brand--compact {color:var(--cw-ink);margin:.35rem 0 1.6rem;}
.cw-brand--compact .cw-brand-name {font-size:29px;}
.cw-topline {margin:.9rem 0 1.3rem;padding-top:1.15rem;border-top:1px solid var(--cw-line-soft);}
.cw-topline-label {color:var(--cw-muted);letter-spacing:.2em;font-size:9px;}
.cw-workspace-tag {color:var(--cw-muted);font-size:10px;}
.cw-workspace-dot {background:var(--cw-accent);box-shadow:0 0 12px var(--cw-accent);}
.cw-hero {grid-template-columns:.94fr 1.2fr;gap:0;min-height:420px;margin:0 0 1.6rem;position:relative;overflow:visible;}
.cw-hero-copy {position:relative;z-index:1;padding:1.2rem 0;}
.cw-eyebrow {color:var(--cw-accent);font-size:10px;letter-spacing:.2em;margin-bottom:1.4rem;}
.cw-hero h1 {font-size:clamp(45px,5.1vw,78px);font-weight:670;line-height:1.01;letter-spacing:-.075em;color:var(--cw-ink);margin-bottom:1.4rem;}
.cw-hero h1 span {color:var(--cw-accent);}
.cw-hero-description {font-size:14px;line-height:1.8;color:var(--cw-muted);max-width:345px;margin-bottom:1.6rem;}
.cw-hero-link {display:inline-flex;align-items:center;gap:20px;color:var(--cw-primary-ink);background:var(--cw-primary);border:1px solid var(--cw-primary);border-radius:8px;padding:12px 18px;text-decoration:none;font-size:12px;font-weight:650;box-shadow:0 8px 30px #00000012;}
.cw-hero-link:hover {color:var(--cw-primary-ink);text-decoration:none;filter:brightness(1.07);}
.cw-hero-link span {font-size:18px;font-weight:400;line-height:1;}
.cw-hero-footnote {color:var(--cw-faint);font-size:10px;margin-top:13px;letter-spacing:.01em;}
.cw-art {margin:0 -2rem 0 -1.3rem;background:transparent;border:0;border-radius:0;overflow:visible;position:relative;}
.cw-art img {width:100%;height:auto;object-fit:contain;max-height:none;}
.cw-art figcaption {color:var(--cw-faint);font-size:9px;font-weight:400;letter-spacing:.04em;text-align:right;padding:0 2rem 0 0;margin-top:-10px;}
.cw-assurances {padding:1.1rem 0 1.5rem;margin-bottom:1.3rem;gap:27px;border-color:var(--cw-line);}
.cw-assurance {color:var(--cw-muted);font-size:11px;gap:9px;}
.cw-assurance img {width:17px;height:17px;}
.cw-section-intro {margin:.5rem 0 .7rem;}
.cw-section-intro h2 {color:var(--cw-ink);font-size:29px;font-weight:600;letter-spacing:-.05em;}
.cw-section-intro p {color:var(--cw-muted);font-size:12px;}
.cw-section-number {color:var(--cw-accent);font-size:9px;letter-spacing:.14em;}
.cw-breadcrumb {color:var(--cw-faint);font-size:9px;letter-spacing:.18em;}
.cw-job-header h1 {color:var(--cw-ink);font-size:clamp(31px,3.4vw,49px);}
.cw-job-header p {color:var(--cw-muted);}
.cw-status {color:var(--cw-accent);background:var(--cw-panel2);border-color:var(--cw-line);border-radius:6px;font-weight:600;}
.cw-status-dot {background:var(--cw-accent);}
.cw-progress li {color:var(--cw-faint);}
.cw-progress li::after {background:var(--cw-line);}
.cw-progress-index {background:var(--cw-panel);border-color:var(--cw-line);color:var(--cw-faint);}
.cw-progress .cw-step-done {color:var(--cw-muted);}
.cw-step-done .cw-progress-index {background:var(--cw-panel2);border-color:var(--cw-line);color:var(--cw-accent);}
.cw-progress .cw-step-active {color:var(--cw-ink);}
.cw-step-active .cw-progress-index {background:var(--cw-primary);border-color:var(--cw-primary);color:var(--cw-primary-ink);}
.cw-progress-note {color:var(--cw-attention);}
.cw-metrics {border-color:var(--cw-line);padding:1.35rem 0;}
.cw-metric {border-color:var(--cw-line);}
.cw-metric-label {color:var(--cw-muted);font-size:9px;letter-spacing:.16em;}
.cw-metric-value {color:var(--cw-ink);font-size:48px;font-weight:500;letter-spacing:-.065em;}
.cw-metric-value--attention {color:var(--cw-attention);}
.cw-metric-caption {color:var(--cw-faint);}
@media (max-width:1100px) {
  [data-testid="stMainBlockContainer"] {padding-left:2rem;padding-right:2rem;}
  .cw-hero h1 {font-size:56px;}
  .cw-hero-description {font-size:13px;}
  .cw-art {margin-right:-1.6rem;}
}
@media (max-width:800px) {
  [data-testid="stMainBlockContainer"] {padding:4.4rem 1.15rem 3rem;}
  .cw-hero {grid-template-columns:1fr;gap:0;margin-bottom:1rem;min-height:0;}
  .cw-hero h1 {font-size:clamp(47px,8.2vw,70px);}
  .cw-hero-copy {padding:.9rem 0 0;}
  .cw-hero-description {max-width:440px;}
  .cw-art {margin:-1.5rem -1rem -1rem 0;max-width:650px;}
  .cw-art img {max-height:410px;}
  .cw-art figcaption {margin-top:-15px;padding-right:1.1rem;}
  .cw-assurances {gap:15px;padding-top:.5rem;}
  .cw-assurance {font-size:10px;}
  .cw-topline-label {font-size:8px;letter-spacing:.13em;}
  .cw-metric-value {font-size:37px;}
  .cw-section-intro h2 {font-size:26px;}
}
</style>
"""


def _active_palette() -> dict[str, str]:
    theme = st.session_state.get("_lumen_row_visual_theme", "dark")
    return _PALETTES.get(theme, _PALETTES["dark"])


_IMMERSIVE_CSS = r"""
<style>
.st-key-lumen_masthead {
  background:var(--cw-panel);border:1px solid var(--cw-line-soft);
  border-radius:999px;padding:1rem 24px 1rem 2rem;box-shadow:0 6px 30px #00000008;
}
.st-key-lumen_masthead [data-testid="stHorizontalBlock"] {align-items:center;gap:1.25rem;}
.st-key-lumen_masthead [data-testid="stColumn"]:has([role="radiogroup"][aria-label="Appearance"]) {min-width:126px!important;}
.st-key-lumen_masthead .st-key-appearance {margin-left:auto!important;}
.st-key-lumen_masthead .cw-brand {margin:0;}
.st-key-lumen_masthead .cw-brand-name {font-size:28px;letter-spacing:-.055em;}
.st-key-lumen_masthead .cw-brand img {width:37px;height:37px;}
.st-key-lumen_masthead [data-testid="stButtonGroup"] [data-testid="stWidgetLabel"] p {font-size:10px;letter-spacing:.09em;line-height:1.3;}
.st-key-lumen_masthead [role="radiogroup"][aria-label="Appearance"] {
  display:flex!important;gap:6px!important;padding:3px!important;
  width:max-content;max-width:100%;border:1px solid var(--cw-line)!important;
  border-radius:999px;background:var(--cw-panel2);overflow:visible;
}
.st-key-lumen_masthead [role="radiogroup"][aria-label="Appearance"] button[data-variant="segmented_control"][role="radio"] {
  flex:0 0 56px!important;width:56px!important;min-width:56px!important;
  height:28px!important;min-height:28px!important;margin:0!important;padding:0 8px!important;
  border:1px solid transparent!important;border-radius:999px!important;box-sizing:border-box;
  background:transparent!important;color:var(--cw-muted)!important;font-weight:600;
  transition:background-color 180ms ease,color 180ms ease,border-color 180ms ease;
}
.st-key-lumen_masthead [role="radiogroup"][aria-label="Appearance"] button[data-variant="segmented_control"][role="radio"] [data-testid="stMarkdownContainer"] p {
  font-size:12px!important;line-height:1!important;margin:0!important;
}
.st-key-lumen_masthead [role="radiogroup"][aria-label="Appearance"] button[data-variant="segmented_control"][role="radio"]:hover {
  background:var(--cw-panel)!important;color:var(--cw-ink)!important;
}
.st-key-lumen_masthead [role="radiogroup"][aria-label="Appearance"] button[data-variant="segmented_control"][role="radio"][aria-checked="true"] {
  background:var(--cw-primary)!important;color:var(--cw-primary-ink)!important;
  border-color:var(--cw-primary)!important;box-shadow:0 2px 8px #00000014;
}
.st-key-lumen_masthead [role="radiogroup"][aria-label="Appearance"] button[data-variant="segmented_control"][role="radio"]:focus-visible,
.st-key-lumen_masthead [role="radiogroup"][aria-label="Appearance"] button[data-variant="segmented_control"][role="radio"][data-focus-visible] {
  outline:3px solid var(--cw-focus)!important;outline-offset:3px!important;
}
.st-key-lumen_masthead [data-testid="stTooltipIcon"] {color:var(--cw-muted)!important;}
.st-key-lumen_masthead [data-testid="stTooltipIcon"] svg {color:inherit!important;}
.cw-theme-dark {display:var(--cw-dark-display)!important;}
.cw-theme-light {display:var(--cw-light-display)!important;}
.cw-theme-icon {position:relative;display:inline-block;width:16px;height:16px;flex-shrink:0;}
.cw-theme-icon img {position:absolute;inset:0;width:100%;height:100%;transition:opacity 200ms ease;}
.cw-theme-icon--dark,.cw-hero-backdrop--dark {opacity:var(--cw-dark-alpha);}
.cw-theme-icon--light,.cw-hero-backdrop--light {opacity:var(--cw-light-alpha);}
.cw-hero.cw-hero-immersive {
  display:block;position:relative;min-height:650px;margin:1.1rem 0 0;
  border:1px solid var(--cw-line-soft);border-radius:28px;overflow:hidden;
  background:var(--cw-paper);isolation:isolate;
}
.cw-hero-backdrop {
  display:block;position:absolute;inset:0;width:100%;height:100%;
  object-fit:cover;object-position:65% center;z-index:-2;transition:opacity 200ms ease;
}
.cw-hero-backdrop--dark {opacity:1;}
.cw-hero-scrim {
  position:absolute;inset:0;z-index:-1;
  background:linear-gradient(90deg,var(--cw-hero-shade) 0%,var(--cw-hero-middle) 32%,transparent 66%);
}
.cw-hero-immersive .cw-hero-copy {width:55%;max-width:620px;padding:5.2rem 0 5rem 3.4rem;}
.cw-hero-immersive .cw-eyebrow {color:var(--cw-accent);font-size:10px;letter-spacing:.15em;margin-bottom:1.7rem;}
.cw-hero-immersive h1 {
  color:var(--cw-ink);font-size:clamp(56px,6vw,86px);line-height:1.025;
  letter-spacing:-.065em;font-weight:650;margin-bottom:1.7rem;
}
.cw-hero-immersive h1 span {color:var(--cw-ink);}
.cw-hero-immersive .cw-hero-description {font-size:14px;line-height:1.8;color:var(--cw-muted);max-width:330px;margin-bottom:1.9rem;}
.cw-hero-immersive .cw-hero-link {
  border-radius:999px;gap:24px;padding:14px 22px;min-height:50px;
  font-size:12px;background:var(--cw-primary);color:var(--cw-primary-ink);
}
.cw-hero-immersive .cw-hero-footnote {font-size:10px;max-width:280px;line-height:1.65;margin-top:15px;}
.cw-hero-local {position:absolute;right:24px;top:22px;display:flex;align-items:center;gap:7px;font-size:10px;color:var(--cw-muted);background:var(--cw-panel);border:1px solid var(--cw-line-soft);border-radius:999px;padding:8px 12px;}
.cw-hero-art-credit {position:absolute;right:22px;bottom:18px;margin:0;padding:5px 9px;border-radius:6px;background:var(--cw-panel);color:var(--cw-muted);font-size:8px;letter-spacing:.025em;}
.cw-assurances {justify-content:center;padding:1.4rem 0;gap:32px;margin-bottom:1.3rem;}
.cw-assurance {font-size:11px;color:var(--cw-muted);}
.cw-section-intro {margin:.5rem 0 .8rem;}
.cw-section-intro h2 {font-size:29px;letter-spacing:-.04em;}
.cw-method-section {padding:1.5rem 0 1rem;}
.cw-method-heading {max-width:640px;margin:0 0 1.7rem;}
.cw-method-heading .cw-eyebrow {margin-bottom:.65rem;}
.cw-method-heading h2 {font-size:34px;line-height:1.2;letter-spacing:-.045em;color:var(--cw-ink);margin:0;}
.cw-method {display:grid;grid-template-columns:repeat(3,1fr);border:1px solid var(--cw-line);border-radius:20px;background:var(--cw-panel);overflow:hidden;}
.cw-method article {padding:1.8rem 1.9rem 2rem;border-left:1px solid var(--cw-line);}
.cw-method article:first-child {border-left:0;}
.cw-method-index {display:block;font-size:13px;letter-spacing:.12em;font-weight:650;color:var(--cw-accent);margin-bottom:1.4rem;}
.cw-method h3 {font-size:23px;letter-spacing:-.035em;color:var(--cw-ink);margin:0 0 .65rem;}
.cw-method p {font-size:13px;line-height:1.8;color:var(--cw-muted);margin:0;}
.cw-product-scope {font-size:11px;line-height:1.6;color:var(--cw-faint);margin:1rem 0 0;}
@media (min-width:1550px) {
  .cw-hero.cw-hero-immersive {min-height:700px;}
  .cw-hero-immersive .cw-hero-copy {padding-top:6.2rem;}
  .cw-hero-immersive h1 {font-size:91px;}
}
@media (max-width:1100px) {
  .cw-hero.cw-hero-immersive {min-height:620px;}
  .cw-hero-immersive .cw-hero-copy {padding:4.8rem 0 4rem 2.6rem;width:62%;}
  .cw-hero-immersive h1 {font-size:62px;}
  .cw-hero-scrim {background:linear-gradient(90deg,var(--cw-hero-shade) 0%,var(--cw-hero-middle) 38%,transparent 74%);}
}
@media (max-width:800px) {
  .st-key-lumen_masthead {padding:.9rem 15px .9rem 1.2rem;border-radius:24px;}
  .st-key-lumen_masthead [data-testid="stHorizontalBlock"] {gap:1rem;align-items:center;}
  .st-key-lumen_masthead .cw-brand-name {font-size:25px;}
  .st-key-lumen_masthead .cw-brand img {width:32px;height:32px;}
  .cw-hero.cw-hero-immersive {min-height:750px;margin-top:.7rem;border-radius:22px;}
  .cw-hero-immersive .cw-hero-copy {width:100%;max-width:none;padding:3.2rem 1.8rem 0;}
  .cw-hero-immersive .cw-eyebrow {margin-bottom:1.3rem;font-size:9px;}
  .cw-hero-immersive h1 {font-size:clamp(49px,8.5vw,66px);max-width:500px;margin-bottom:1.25rem;}
  .cw-hero-immersive .cw-hero-description {font-size:13px;max-width:340px;margin-bottom:1.4rem;}
  .cw-hero-immersive .cw-hero-footnote {max-width:310px;font-size:9px;}
  .cw-hero-backdrop {inset:auto 0 0;height:57%;object-position:67% center;}
  .cw-hero-scrim {background:linear-gradient(180deg,var(--cw-hero-shade) 0%,var(--cw-hero-shade) 40%,var(--cw-hero-middle) 53%,transparent 76%);}
  .cw-hero-local {right:15px;top:12px;font-size:8px;padding:5px 9px;}
  .cw-hero-art-credit {right:12px;bottom:12px;font-size:7px;}
  .cw-assurances {justify-content:flex-start;gap:14px;padding:1.1rem 0;}
  .cw-assurance {font-size:10px;}
  .cw-section-intro h2 {font-size:25px;}
  .cw-method-heading h2 {font-size:29px;}
  .cw-method article {padding:1.3rem 1.1rem 1.5rem;}
  .cw-method h3 {font-size:21px;}
  .cw-method p {font-size:12px;}
}
@media (max-width:460px) {
  .st-key-lumen_masthead {padding:.8rem 15px .8rem .9rem;}
  .st-key-lumen_masthead .cw-brand-name {font-size:22px;}
  .st-key-lumen_masthead .cw-brand-byline {font-size:7px;letter-spacing:.07em;}
  .st-key-lumen_masthead .cw-brand {gap:7px;}
  .cw-hero-immersive .cw-hero-copy {padding-left:1.25rem;padding-right:1.25rem;}
  .cw-hero-immersive h1 {font-size:48px;}
  .cw-hero.cw-hero-immersive {min-height:770px;}
  .cw-method {grid-template-columns:1fr;}
  .cw-method article {border-left:0;border-top:1px solid var(--cw-line);padding:1.5rem;}
  .cw-method article:first-child {border-top:0;}
  .cw-method-index {margin-bottom:.8rem;}
}
</style>
"""


_MOTION_CSS = r"""
<style>
/* Match the photograph's cover crop, then move only its decorative records. */
.cw-motion-viewport {
  position:absolute;inset:0;container-type:size;overflow:hidden;pointer-events:none;z-index:-2;
}
.cw-motion-scene {
  position:absolute;width:max(100cqw,177.872340426cqh);height:max(56.220095694cqw,100cqh);
  left:65%;top:50%;transform:translate(-65%,-50%);container-type:size;
}
.cw-flow-record {
  position:absolute;left:var(--still-x);top:var(--still-y);width:6.3%;height:7.5%;
  border:1px solid var(--cw-motion-lilac);border-radius:.45cqw;
  background:var(--cw-motion-glass);box-shadow:0 .3cqw 1cqw #160b252b,inset 0 0 .7cqw #ffffff12;
  transform:translate(-50%,-50%) skewY(12deg);opacity:.8;
  animation:cw-record-journey 10.8s linear infinite;animation-delay:var(--packet-delay);
}
.cw-record-row {
  position:absolute;left:var(--raw-left);width:var(--raw-width);height:7%;border-radius:20px;
  background:var(--cw-motion-raw);box-shadow:0 0 .35cqw #e4c4ff44;
  animation:cw-align-rows 10.8s linear infinite;animation-delay:var(--packet-delay);
}
.cw-record-row--one {top:23%;--raw-left:13%;--raw-width:48%;}
.cw-record-row--two {top:46%;--raw-left:22%;--raw-width:62%;}
.cw-record-row--three {top:69%;--raw-left:13%;--raw-width:34%;}
.cw-record-check {
  position:absolute;right:8%;top:10%;width:16%;aspect-ratio:1;border-radius:50%;
  background:var(--cw-motion-clean);box-shadow:0 0 .6cqw #9af0d044;opacity:0;
  animation:cw-approve-record 10.8s linear infinite;animation-delay:var(--packet-delay);
}
.cw-record-check::after {
  content:"";position:absolute;left:28%;top:17%;width:30%;height:49%;
  border:solid var(--cw-panel);border-width:0 1.5px 1.5px 0;transform:rotate(43deg);
}
.cw-scanner-glow {
  position:absolute;left:64.8%;top:36%;width:10%;height:25%;
  transform:translate(-50%,-50%) rotate(-8deg);border-radius:50%;
  background:radial-gradient(ellipse,var(--cw-motion-glow),transparent 68%);
  opacity:.3;animation:cw-inspection-glow 3.6s ease-in-out infinite;
}
.cw-scanner-sweep {
  position:absolute;left:62%;top:28%;width:6.8%;height:18%;
  border-radius:48% 48% 12% 12%;opacity:0;
  background:linear-gradient(180deg,transparent 55%,var(--cw-motion-glow) 90%,transparent);
  animation:cw-inspection-sweep 3.6s ease-in-out infinite;
}
.cw-motion-control,.cw-motion-reduced {
  position:absolute;right:22px;bottom:44px;z-index:3;display:inline-flex;align-items:center;
  gap:7px;min-height:32px;padding:6px 10px;border:1px solid var(--cw-line);
  border-radius:999px;background:var(--cw-panel);color:var(--cw-muted);
  font-size:10px;line-height:1.4;cursor:pointer;user-select:none;
}
.cw-motion-control:hover {color:var(--cw-ink);border-color:var(--cw-accent);}
.cw-motion-control:has(input:focus-visible) {outline:3px solid var(--cw-focus);outline-offset:3px;}
.cw-motion-control input.cw-motion-toggle {
  width:13px;height:13px;min-width:13px;margin:0;accent-color:var(--cw-primary);cursor:pointer;
}
.cw-motion-paused,.cw-motion-reduced {display:none;}
.cw-motion-toggle:checked ~ .cw-motion-running {display:none;}
.cw-motion-toggle:checked ~ .cw-motion-paused {display:inline;}
.cw-hero:has(.cw-motion-toggle:checked) .cw-motion-scene * {animation-play-state:paused!important;}
@keyframes cw-record-journey {
  0% {left:38.9%;top:19.1%;opacity:0;transform:translate(-50%,-50%) rotate(-14deg) skewY(8deg) scale(.82);border-color:var(--cw-motion-lilac);}
  6% {opacity:.78;}
  20% {left:43.1%;top:30.3%;transform:translate(-50%,-50%) rotate(4deg) skewY(12deg) scale(.93);}
  38% {left:53.5%;top:36.7%;opacity:.9;transform:translate(-50%,-50%) rotate(-4deg) skewY(12deg);}
  50% {left:64.3%;top:42.5%;opacity:.35;border-color:var(--cw-motion-lilac);}
  54% {opacity:0;}
  59% {left:73%;top:47%;opacity:0;border-color:var(--cw-motion-clean);transform:translate(-50%,-50%) rotate(-9deg) skewY(-8deg);}
  65% {opacity:.92;}
  88% {left:85.8%;top:53.1%;opacity:.92;}
  100% {left:91.5%;top:56.9%;opacity:0;border-color:var(--cw-motion-clean);transform:translate(-50%,-50%) rotate(-9deg) skewY(-8deg);}
}
@keyframes cw-align-rows {
  0%,50% {left:var(--raw-left);width:var(--raw-width);background:var(--cw-motion-raw);}
  27%,38% {background:var(--cw-motion-lilac);}
  59%,100% {left:13%;width:60%;background:var(--cw-motion-clean);}
}
@keyframes cw-approve-record {0%,55% {opacity:0;} 62%,100% {opacity:1;}}
@keyframes cw-inspection-glow {0%,100% {opacity:.22;} 45%,65% {opacity:.8;}}
@keyframes cw-inspection-sweep {
  0%,20% {opacity:0;transform:translateY(-12%);}
  40% {opacity:.65;}
  75%,100% {opacity:0;transform:translateY(48%);}
}
@media (max-width:800px) {
  .cw-motion-viewport {inset:auto 0 0;height:57%;}
  .cw-motion-scene {left:67%;transform:translate(-67%,-50%);}
  .cw-motion-control,.cw-motion-reduced {right:12px;bottom:35px;font-size:9px;}
}
@media (prefers-reduced-motion:reduce) {
  .cw-motion-scene * {animation:none!important;}
  .cw-motion-control {display:none;}
  .cw-motion-reduced {display:inline-flex;cursor:default;}
  .cw-flow-record--reviewed {border-color:var(--cw-motion-clean);transform:translate(-50%,-50%) rotate(-9deg) skewY(-8deg);}
  .cw-flow-record--reviewed .cw-record-row {left:13%;width:60%;background:var(--cw-motion-clean);}
  .cw-flow-record--reviewed .cw-record-check {opacity:1;}
}
</style>
"""


def _hero_motion() -> str:
    """A decorative, CSS-only loop; the checkbox pauses every moving layer."""
    records = []
    for delay, x, y, reviewed in (
        ("0s", "45%", "31.5%", False),
        ("-3.6s", "57%", "38.5%", False),
        ("-7.2s", "83%", "52%", True),
    ):
        modifier = " cw-flow-record--reviewed" if reviewed else ""
        records.append(
            f'<div class="cw-flow-record{modifier}" style="--packet-delay:{delay};--still-x:{x};--still-y:{y};">'
            '<span class="cw-record-row cw-record-row--one"></span>'
            '<span class="cw-record-row cw-record-row--two"></span>'
            '<span class="cw-record-row cw-record-row--three"></span>'
            '<span class="cw-record-check"></span></div>'
        )
    return (
        '<div id="cw-record-flow" class="cw-motion-viewport" aria-hidden="true">'
        '<div class="cw-motion-scene"><div class="cw-scanner-glow"></div>'
        '<div class="cw-scanner-sweep"></div>' + "".join(records) + '</div></div>'
        '<label class="cw-motion-control">'
        '<input class="cw-motion-toggle" type="checkbox" aria-controls="cw-record-flow"/>'
        '<span class="cw-motion-running">Pause animation</span>'
        '<span class="cw-motion-paused">Resume animation</span></label>'
        '<span class="cw-motion-reduced">Motion reduced</span>'
    )


@st.cache_data(show_spinner=False)
def _cached_hero_data(path: str, modified_ns: int) -> str:
    """Read each original local image once per file version, across reruns."""
    del modified_ns  # Its value deliberately participates in the cache key.
    return "data:image/png;base64," + b64encode(Path(path).read_bytes()).decode("ascii")


def _hero_background() -> str:
    """Keep both scenes mounted so changing appearance only changes opacity."""
    images = []
    for theme in ("dark", "light"):
        path = Path(__file__).resolve().parents[1] / "assets" / f"lumenrow-hero-{theme}.png"
        image = _cached_hero_data(str(path), path.stat().st_mtime_ns)
        images.append(
            f'<img class="cw-hero-backdrop cw-hero-backdrop--{theme}" src="{image}" '
            'alt="" aria-hidden="true" loading="eager" decoding="sync" draggable="false"/>'
        )
    return "".join(images)


def _theme_icon(svg: str) -> str:
    """Preload both small icon palettes without rebuilding the landing markup."""
    images = []
    for theme in ("dark", "light"):
        image = _svg_image(svg, color=_PALETTES[theme]["accent"])
        images.append(image.replace("<img ", f'<img class="cw-theme-icon--{theme}" ', 1))
    return '<span class="cw-theme-icon" aria-hidden="true">' + "".join(images) + "</span>"


_HUB_CSS = r"""
<style>
/* A shared identity and native controls keep the product and review hub together. */
.st-key-lumen_masthead .cw-brand {gap:14px;}
.st-key-lumen_masthead .cw-brand img {width:62px;height:62px;}
.st-key-lumen_masthead .cw-brand-name {font-size:30px;}
.st-key-lumen_masthead .cw-brand-byline {font-size:10px;letter-spacing:.09em;margin-top:7px;}
button[aria-label^="Help for"] svg {stroke:var(--cw-muted)!important;}
.cw-brand--compact img {width:48px;height:48px;}
.cw-job-mark img {width:29px;height:29px;}
.cw-metric-value--unavailable {font-size:clamp(18px,2.2vw,28px);line-height:1.7;color:var(--cw-muted);letter-spacing:-.03em;}
.st-key-lumen_workspace_nav {
  padding:.15rem 0 1.1rem;border-bottom:1px solid var(--cw-line);margin-bottom:.7rem;
}
.st-key-lumen_workspace_nav [data-testid="stHorizontalBlock"] {gap:.65rem;align-items:center;}
.st-key-lumen_workspace_nav [data-testid="stColumn"] {flex:0 0 auto!important;min-width:0!important;width:auto!important;}
.st-key-lumen_workspace_nav [data-testid="stColumn"]:last-child {margin-left:auto;}
.st-key-lumen_workspace_nav button {width:auto!important;min-height:38px;border-radius:10px;font-size:13px;padding:.45rem .8rem;box-shadow:none;}
.st-key-lumen_workspace_nav button[kind="primary"] {background:var(--cw-panel2);border-color:var(--cw-line);color:var(--cw-ink);}
.st-key-lumen_workspace_nav button[kind="secondary"] {background:transparent;border-color:transparent;color:var(--cw-muted);}
.st-key-lumen_workspace_nav button[kind="secondary"]:hover {background:var(--cw-panel2);color:var(--cw-ink);}
.cw-hub-intro {margin:.6rem 0 1.4rem;}
.cw-hub-intro .cw-eyebrow {margin:0 0 .65rem;font-size:10px;color:var(--cw-accent);}
.cw-hub-intro h1 {font-size:clamp(30px,3.2vw,44px)!important;line-height:1.12;letter-spacing:-.05em;font-weight:620;padding:0;margin:0 0 .85rem;}
.cw-hub-intro p {color:var(--cw-muted);font-size:14px;line-height:1.6;margin:0;}
.st-key-lumen_hub_actions {margin:.15rem 0 1.3rem;}
.st-key-lumen_hub_actions [data-testid="stHorizontalBlock"] {gap:1.25rem!important;align-items:stretch;}
.st-key-lumen_review_card,.st-key-lumen_sample_card {
  position:relative;border:1px solid var(--cw-line)!important;border-radius:23px!important;
  padding:1.9rem!important;min-height:285px;background:var(--cw-panel)!important;
  box-shadow:0 10px 35px #00000008;isolation:isolate;overflow:hidden;
}
.st-key-lumen_review_card {background:linear-gradient(130deg,var(--cw-panel),var(--cw-panel2))!important;}
.st-key-lumen_review_card::before,.st-key-lumen_sample_card::before {
  content:"";display:block;width:29px;height:29px;background:var(--cw-accent);margin-bottom:.2rem;
  mask:center / contain no-repeat;flex-shrink:0;
}
.st-key-lumen_review_card::before {
  mask-image:url('data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"%3E%3Cpath d="M12 15V3m-4 4 4-4 4 4M4 14v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5" stroke="black" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/%3E%3C/svg%3E');
}
.st-key-lumen_sample_card::before {
  mask-image:url('data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"%3E%3Cpath d="M9 3h6m-5 0v7l-5 8a2 2 0 0 0 1.7 3h10.6a2 2 0 0 0 1.7-3l-5-8V3M8 15h8" stroke="black" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/%3E%3C/svg%3E');
}
.st-key-lumen_review_card::after,.st-key-lumen_sample_card::after {
  content:"";position:absolute;right:-44px;top:-64px;width:175px;height:175px;border-radius:50%;
  border:1px solid var(--cw-line);box-shadow:0 0 0 24px color-mix(in srgb,var(--cw-accent) 3%,transparent),0 0 0 48px color-mix(in srgb,var(--cw-accent) 2%,transparent);
  z-index:-1;pointer-events:none;
}
.st-key-lumen_review_card h2,.st-key-lumen_sample_card h2,
.st-key-lumen_review_card h3,.st-key-lumen_sample_card h3 {font-size:25px!important;letter-spacing:-.04em!important;padding:0!important;}
.st-key-lumen_review_card [data-testid="stMarkdownContainer"] p,
.st-key-lumen_sample_card [data-testid="stMarkdownContainer"] p {font-size:14px;color:var(--cw-muted);max-width:440px;}
.cw-action-icon {display:inline-flex;align-items:center;justify-content:center;width:42px;height:42px;border-radius:12px;background:var(--cw-panel2);color:var(--cw-accent);font-size:25px;margin-bottom:.35rem;}
.cw-action-icon img,.cw-action-icon svg {width:25px;height:25px;}
.st-key-lumen_hub_actions button {border-radius:11px;min-height:43px;}
.st-key-lumen_saved_reviews {margin-top:.8rem;}
.st-key-lumen_saved_reviews h2,.st-key-lumen_saved_reviews h3 {font-size:24px!important;letter-spacing:-.04em;}
.st-key-lumen_saved_filters {padding:.1rem 0 .5rem;}
.st-key-lumen_saved_filters [data-testid="stHorizontalBlock"] {align-items:end;gap:1rem;}
[class*="st-key-lumen_review_row_"] {
  padding:1.25rem 1.4rem!important;background:var(--cw-panel)!important;
  border:1px solid var(--cw-line)!important;border-radius:17px!important;
}
[class*="st-key-lumen_review_row_"] [data-testid="stHorizontalBlock"] {gap:1.1rem;align-items:center;}
.cw-review-name {font-size:16px;font-weight:630;letter-spacing:-.02em;color:var(--cw-ink);margin:0 0 5px;overflow-wrap:anywhere;}
.cw-review-meta {font-size:12px;color:var(--cw-muted);line-height:1.65;}
[class*="st-key-lumen_review_row_"] [data-testid="stCaptionContainer"] p {font-size:12px;}
[class*="st-key-lumen_review_row_"] button {min-height:40px;padding:.45rem .75rem;font-size:12px;border-radius:10px;}
.cw-draft-steps {display:flex;gap:1.7rem;list-style:none;padding:0;margin:1.2rem 0 1.8rem;color:var(--cw-muted);font-size:14px;}
.cw-draft-steps li {display:flex;align-items:center;gap:9px;}
.cw-draft-steps b,.cw-draft-steps .step-number {display:grid;place-items:center;min-width:29px;height:29px;border-radius:50%;border:1px solid var(--cw-line);font-size:12px;font-weight:600;}
.cw-draft-steps [aria-current="step"] {color:var(--cw-ink);font-weight:650;}
.cw-draft-steps [aria-current="step"] b,.cw-draft-steps [aria-current="step"] .step-number {background:var(--cw-primary);border-color:var(--cw-primary);color:var(--cw-primary-ink);}
.st-key-lumen_wizard {border:1px solid var(--cw-line)!important;background:var(--cw-panel)!important;border-radius:23px!important;padding:2rem!important;}
.st-key-lumen_wizard [data-testid="stFileUploaderDropzone"] {min-height:170px;display:flex;align-items:center;border-color:var(--cw-muted);padding:1.7rem;border-radius:16px;}
.st-key-lumen_wizard_actions {border-top:1px solid var(--cw-line);padding-top:1.2rem;margin-top:.8rem;}
.st-key-lumen_wizard_actions [data-testid="stHorizontalBlock"] {gap:1rem;align-items:center;}
.st-key-lumen_wizard_actions button {border-radius:11px;}
.st-key-lumen_wizard [data-testid="stCaptionContainer"] p {font-size:12px;}
.st-key-lumen_wizard [data-testid="stTextInputRootElement"],
.st-key-lumen_saved_filters [data-testid="stTextInputRootElement"] {border-color:var(--cw-muted)!important;}
@media(max-width:850px) {
  .st-key-lumen_masthead .cw-brand img {width:52px;height:52px;}
  .st-key-lumen_masthead .cw-brand-name {font-size:27px;}
  .st-key-lumen_masthead .cw-brand-byline {font-size:9px;letter-spacing:.04em;}
  .st-key-lumen_hub_actions [data-testid="stHorizontalBlock"] {flex-wrap:wrap;}
  .st-key-lumen_hub_actions [data-testid="stColumn"] {width:100%!important;flex:1 1 100%!important;min-width:0!important;}
  .st-key-lumen_review_card,.st-key-lumen_sample_card {min-height:0;padding:1.5rem!important;}
  .st-key-lumen_saved_filters [data-testid="stHorizontalBlock"] {flex-wrap:wrap;}
  .st-key-lumen_saved_filters [data-testid="stColumn"] {min-width:240px!important;flex:1 1 240px!important;}
  [class*="st-key-lumen_review_row_"] [data-testid="stHorizontalBlock"] {flex-wrap:wrap;}
  [class*="st-key-lumen_review_row_"] [data-testid="stColumn"]:first-child {flex:1 1 100%!important;width:100%!important;}
  [class*="st-key-lumen_review_row_"] [data-testid="stColumn"] {min-width:100px!important;flex:1 1 100px!important;}
}
@media(max-width:540px) {
  .st-key-lumen_masthead .cw-brand img {width:48px;height:48px;}
  .st-key-lumen_masthead .cw-brand-name {font-size:23px;}
  .st-key-lumen_masthead .cw-brand-byline {font-size:9px;letter-spacing:0;max-width:140px;line-height:1.4;}
  .st-key-lumen_masthead .cw-brand {gap:9px;}
  .st-key-lumen_workspace_nav [data-testid="stHorizontalBlock"] {flex-wrap:wrap;gap:.5rem;}
  .st-key-lumen_workspace_nav [data-testid="stColumn"] {flex:1 1 40%!important;min-width:100px!important;}
  .st-key-lumen_workspace_nav [data-testid="stColumn"]:last-child {margin-left:0;}
  .st-key-lumen_wizard {padding:1.25rem!important;border-radius:18px!important;}
  .cw-draft-steps {gap:1rem;font-size:12px;}
  .cw-draft-steps li {gap:6px;}
  .cw-hub-intro h1 {font-size:31px!important;}
  [class*="st-key-lumen_review_row_"] {padding:1.1rem!important;}
}
</style>
"""


_ROW_MARK = ('<svg viewBox="0 0 64 64" aria-hidden="true" fill="none">'
             '<defs><linearGradient id="glass" x1="10" y1="8" x2="55" y2="57" gradientUnits="userSpaceOnUse">'
             '<stop stop-color="currentColor" stop-opacity=".38"/><stop offset="1" stop-color="currentColor" stop-opacity=".08"/>'
             '</linearGradient><linearGradient id="facet" x1="31" y1="10" x2="54" y2="50" gradientUnits="userSpaceOnUse">'
             '<stop stop-color="currentColor" stop-opacity=".5"/><stop offset="1" stop-color="currentColor" stop-opacity=".12"/>'
             '</linearGradient></defs>'
             '<path d="M32 3.5 56 17.5v29L32 60.5 8 46.5v-29Z" fill="url(#glass)" stroke="currentColor" stroke-opacity=".7" stroke-width="1.5" stroke-linejoin="round"/>'
             '<path d="m32 10 18 10.5v22L32 53V10Z" fill="url(#facet)"/>'
             '<path d="M14 21 32 10l18 10.5M32 10v43M14 43l18 10 18-10.5" stroke="currentColor" stroke-opacity=".65" stroke-width="1.3" stroke-linejoin="round"/>'
             '<path d="M16 25h8m-11 8h11m-6 8h6" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>'
             '<path d="m37 32 4.5 4.5L51 25" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'
             '<path d="m32 6 1.6 2.4L36 10l-2.4 1.6L32 14l-1.6-2.4L28 10l2.4-1.6Z" fill="currentColor"/>'
             '</svg>')
_CHECK = '<svg viewBox="0 0 20 20" aria-hidden="true" fill="none"><path d="m4.5 10 3.5 3.5 7.5-7.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>'
_SHIELD = '<svg viewBox="0 0 20 20" aria-hidden="true" fill="none"><path d="m10 2.5 6 2.4v4.3c0 3.4-2.3 5.8-6 8.3-3.7-2.5-6-4.9-6-8.3V4.9l6-2.4Z" stroke="currentColor" stroke-width="1.3"/><path d="m7 9.5 2 2 4-4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>'
_HISTORY = '<svg viewBox="0 0 20 20" aria-hidden="true" fill="none"><path d="M3 9a7 7 0 1 1 1.5 5.3M3 4v5h5m2-3v4l2.5 1.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>'

def apply_theme(theme: str = "dark", landing: bool = False) -> None:
    """Style native widgets; reserve navigation and tools for the workspace."""
    theme = "light" if theme == "light" else "dark"
    # Theme belongs to this browser session; never mutate Streamlit's global
    # configuration or another user's palette to change presentation.
    st.session_state["_lumen_row_visual_theme"] = theme
    palette = _PALETTES[theme]
    variables = ";".join(f"--cw-{name}:{value}" for name, value in palette.items())
    aliases = f"--cw-forest:{palette['ink']};--cw-soft:{palette['panel2']};--cw-focus:{palette['accent']}"
    layers = (
        f"--cw-dark-alpha:{int(theme == 'dark')};--cw-light-alpha:{int(theme == 'light')};"
        f"--cw-dark-display:{'inline-flex' if theme == 'dark' else 'none'};"
        f"--cw-light-display:{'inline-flex' if theme == 'light' else 'none'}"
    )
    landing_css = """
<style>
[data-testid="stSidebar"],
[data-testid="stHeader"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="stExpandSidebarButton"],
button[aria-label="Expand sidebar"] {display:none!important;}
[data-testid="stMainBlockContainer"] {padding-top:2.5rem;}
</style>
""" if landing else ""
    st.html(_CSS + f"<style>:root{{{variables};{aliases};{layers};color-scheme:{theme};}}</style>" + _THEME_CSS + _IMMERSIVE_CSS + _HUB_CSS + (_MOTION_CSS if landing else "") + landing_css)


def render_brand(compact: bool = False) -> None:
    """Render the appropriate size and this session's palette for the mark."""
    modifier = " cw-brand--compact" if compact else ""
    mark = _svg_image(_ROW_MARK, color=_active_palette()["accent"])
    st.html(
        f'<div class="cw-brand{modifier}" aria-label="{BRAND_NAME}, data quality workspace">'
        f'{mark}'
        f'<div><div class="cw-brand-name">{BRAND_NAME.lower()}</div>'
        f'<div class="cw-brand-byline">{BRAND_TAGLINE}</div></div></div>'
    )


def render_landing(saved_count: int = 0, theme: str = "dark") -> None:
    """Introduce the product and link to its separate working application."""
    # The signature stays compatible, but appearance now changes CSS only.
    # Identical HTML on each rerun lets Streamlit retain the decoded images.
    del saved_count, theme
    scene = _hero_background()
    shield = _theme_icon(_SHIELD)
    check = _theme_icon(_CHECK)
    history = _theme_icon(_HISTORY)
    st.html(
        '<section class="cw-hero cw-hero-immersive" aria-labelledby="cw-landing-title">'
        f'{scene}{_hero_motion()}<div class="cw-hero-scrim" aria-hidden="true"></div>'
        '<div class="cw-hero-local"><span class="cw-workspace-dot"></span>Your review. Your rules.</div>'
        '<div class="cw-hero-copy"><p class="cw-eyebrow">LUMEN ROW / A CLEARER WAY FORWARD</p>'
        '<h1 id="cw-landing-title">Good data.<br><span>Clear decisions.</span></h1>'
        '<p class="cw-hero-description">A little clarity changes everything. Turn a messy customer file into a reviewed, validated import — with you in control of every change.</p>'
        '<a class="cw-hero-link cw-theme-dark" href="?view=workspace&amp;appearance=dark" target="_self">Open workspace <span aria-hidden="true">↗</span></a>'
        '<a class="cw-hero-link cw-theme-light" href="?view=workspace&amp;appearance=light" target="_self">Open workspace <span aria-hidden="true">↗</span></a>'
        '<p class="cw-hero-footnote">Your original stays safe. Every fix gets your approval.</p></div>'
        '<p class="cw-hero-art-credit">An original visual for Lumen Row</p>'
        '</section>'
        '<div class="cw-assurances" aria-label="How your data is handled">'
        f'<div class="cw-assurance">{shield}<span>Originals stay intact</span></div>'
        f'<div class="cw-assurance">{check}<span>Every change, reviewed</span></div>'
        f'<div class="cw-assurance">{history}<span>Resume whenever you need</span></div></div>'
        '<section class="cw-method-section" aria-labelledby="cw-method-title">'
        '<div class="cw-method-heading"><p class="cw-eyebrow">THE WAY IT WORKS</p>'
        '<h2 id="cw-method-title">Three steps. A clearer outcome.</h2></div>'
        '<div class="cw-method">'
        '<article><span class="cw-method-index">01 / SEE THE WHOLE PICTURE</span>'
        '<h3>Inspect</h3><p>Find missing values, duplicate records, date-format issues, and inconsistent categories against your import rules.</p></article>'
        '<article><span class="cw-method-index">02 / KEEP YOUR SAY</span>'
        '<h3>Review</h3><p>Compare proposed repairs with the original. Supply missing facts and approve the exact changes before they are applied.</p></article>'
        '<article><span class="cw-method-index">03 / MOVE FORWARD</span>'
        '<h3>Export</h3><p>Run the final checks, approve export, and download a validated customer CSV with a clear audit trail.</p></article>'
        '</div><p class="cw-product-scope">CSV, TSV, Excel, JSON and JSON Lines in. Reviewed CSV out. Your original file stays intact, and saved jobs are ready when you return.</p>'
        '</section>'
    )


def render_job_header(name: str, status_label: str, mode_label: str) -> None:
    """Display a human-readable job name; UUIDs belong outside this component."""
    mark = _svg_image(_ROW_MARK, color=_active_palette()["accent"])
    st.html(
        f'<header class="cw-job-header"><div class="cw-breadcrumb"><span class="cw-job-mark">{mark}</span>Your workspace / Customer import</div>'
        f'<div class="cw-job-title-row"><h1>{escape(str(name))}</h1>'
        f'<span class="cw-status"><span class="cw-status-dot"></span>{escape(str(status_label))}</span></div>'
        f'<p>{escape(str(mode_label))} <span aria-hidden="true">&nbsp;·&nbsp;</span> Progress saved locally</p></header>'
    )


def render_workflow_progress(status: str) -> None:
    """Render five plain-language stages with explicit active/completed states."""
    positions = {
        "investigating": 1,
        "awaiting_clarification": 2,
        "awaiting_repair_approval": 2,
        "approved": 3,
        "validating": 3,
        "awaiting_export_approval": 4,
        "exporting": 4,
        "complete": 5,
    }
    current = positions.get(status)
    items = []
    for index, label in enumerate(("Import", "Inspect", "Review", "Validate", "Export")):
        done = current is not None and index < current
        active = index == current
        modifier = " cw-step-done" if done else " cw-step-active" if active else ""
        aria_current = ' aria-current="step"' if active else ""
        accessibility = "completed" if done else "current step" if active else "pending"
        icon = _svg_image(_CHECK, color=_active_palette()["accent"]) if done else str(index + 1)
        items.append(
            f'<li class="{modifier.strip()}"{aria_current} aria-label="{label}: {accessibility}">'
            f'<span class="cw-progress-index" aria-hidden="true">{icon}</span><span>{label}</span></li>'
        )
    note = ""
    if status == "blocked":
        note = '<p class="cw-progress-note">This job is paused. Review the message below to see what needs attention.</p>'
    elif status == "cancelled":
        note = '<p class="cw-progress-note">This job has been cancelled. Its saved history is still available.</p>'
    st.html('<ol class="cw-progress" aria-label="Workflow progress">' + "".join(items) + "</ol>" + note)


def render_summary_metrics(records: int, blockers: int | None, changes: int, *,
                           blocker_caption: str = "At the current validation stage") -> None:
    """A compact editorial scorecard using actual job values, never demo counts."""
    count = None if blockers is None else max(0, int(blockers))
    entries = [
        ("Records", f"{max(0, int(records)):,}", "In your original file", ""),
        ("Blocking issues", "Not available" if count is None else f"{count:,}",
         "Validation could not be verified" if count is None else escape(blocker_caption),
         " cw-metric-value--unavailable" if count is None else " cw-metric-value--attention" if count else ""),
        ("Proposed changes", f"{max(0, int(changes)):,}", "In the saved repair plan", ""),
    ]
    content = "".join(
        f'<div class="cw-metric"><div class="cw-metric-label">{label}</div>'
        f'<div class="cw-metric-value{modifier}">{value}</div>'
        f'<div class="cw-metric-caption">{caption}</div></div>'
        for label, value, caption, modifier in entries
    )
    st.html(f'<section class="cw-metrics" aria-label="Job at a glance">{content}</section>')
