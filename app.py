"""FreightIQ — Streamlit UI for the freight-rate-intelligence pipeline.

Layout: single-column main area (form on top, results below); sidebar
hosts brand + examples + disclaimer. Weight-calculator inputs live
outside `st.form(...)` so the live chargeable-weight strip updates on
every keystroke; the submit button's form wraps only the fields that
can wait for a batch submit.
"""
from __future__ import annotations

import logging
from typing import Any

import streamlit as st

from pipeline import RecommendationResult, run_pipeline

logger = logging.getLogger("app")

PAGE_TITLE = "FreightIQ — Rate Intelligence"
PAGE_ICON = "📦"
TAGLINE = "Rate intelligence for small-business shippers"

# ---- Helper functions (also imported by tests/test_ui_smoke.py) ----

def compute_weights(
    gross_weight_kg: float,
    length_cm: float,
    width_cm: float,
    height_cm: float,
) -> dict[str, Any]:
    """Compute volume + chargeable weight + basis per CLAUDE.md §Critical formulas."""
    volume_weight_kg = round((length_cm * width_cm * height_cm) / 5000, 2)
    chargeable_weight_kg = round(max(gross_weight_kg, volume_weight_kg), 2)
    # Ties resolve to "gross" (actual weight) — volume only dominates when strictly greater.
    weight_basis = "volume" if volume_weight_kg > gross_weight_kg else "gross"
    return {
        "volume_weight_kg": volume_weight_kg,
        "chargeable_weight_kg": chargeable_weight_kg,
        "weight_basis": weight_basis,
    }


def build_shipment_input(
    *,
    product: str,
    gross_weight_kg: float,
    length_cm: float,
    width_cm: float,
    height_cm: float,
    origin: str,
    destination: str,
    urgency: str,
) -> dict[str, Any]:
    """Build a ShipmentInput dict conforming to CLAUDE.md §Data contracts."""
    weights = compute_weights(gross_weight_kg, length_cm, width_cm, height_cm)
    return {
        "product": product,
        "gross_weight_kg": gross_weight_kg,
        "length_cm": length_cm,
        "width_cm": width_cm,
        "height_cm": height_cm,
        **weights,
        "origin": origin,
        "destination": destination,
        "urgency": urgency,
    }


# ---- Trust band helpers ----

def _trust_band(score: int) -> tuple[str, str, str]:
    """Return (label, colour_token, emoji) for a trust_score."""
    if score >= 80:
        return ("Verified", "#2dd98b", "✓")
    if score >= 50:
        return ("Caution", "#f5a623", "⚠")
    return ("High risk", "#f25353", "✗")


def _best_value_label(rank: int, trust: int) -> str:
    if rank == 1 and trust >= 80:
        return "Best value"
    label, _, _ = _trust_band(trust)
    return label


# ---- Example queries (sidebar chips) ----

EXAMPLES = [
    {
        "label": "Delhi → Rotterdam · 200 kg",
        "product": "electronics",
        "gross_weight_kg": 180.0,
        "length_cm": 100.0,
        "width_cm": 100.0,
        "height_cm": 100.0,
        "origin": "Delhi",
        "destination": "Rotterdam",
        "urgency": "standard",
    },
    {
        "label": "Mumbai → New York · 50 kg",
        "product": "textiles",
        "gross_weight_kg": 50.0,
        "length_cm": 60.0,
        "width_cm": 60.0,
        "height_cm": 40.0,
        "origin": "Mumbai",
        "destination": "New York",
        "urgency": "standard",
    },
    {
        "label": "Shanghai → Dubai · 800 kg",
        "product": "machinery",
        "gross_weight_kg": 800.0,
        "length_cm": 150.0,
        "width_cm": 120.0,
        "height_cm": 100.0,
        "origin": "Shanghai",
        "destination": "Dubai",
        "urgency": "standard",
    },
]


def _load_example(index: int) -> None:
    """Copy example fields into session_state and trigger a rerun."""
    ex = EXAMPLES[index]
    for key in (
        "product",
        "gross_weight_kg",
        "length_cm",
        "width_cm",
        "height_cm",
        "origin",
        "destination",
        "urgency",
    ):
        st.session_state[key] = ex[key]
    # Drop any stale result so the new inputs get a fresh run when submitted.
    st.session_state["result"] = None


# ---- Session-state bootstrap ----

def _init_state() -> None:
    defaults = {
        "product": "electronics",
        "gross_weight_kg": 180.0,
        "length_cm": 100.0,
        "width_cm": 100.0,
        "height_cm": 100.0,
        "origin": "",
        "destination": "",
        "urgency": "standard",
        "result": None,
        "error": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ---- CSS injection (design system) ----

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --bg: #06070a;
  --surface: #0d0f14;
  --surface-2: #141720;
  --surface-3: #1c2029;
  --border: #ffffff0d;
  --border-md: #ffffff18;
  --accent: #e8ff5a;
  --green: #2dd98b;
  --amber: #f5a623;
  --red: #f25353;
  --text-1: #f4f5f7;
  --text-2: #9ba3b4;
  --text-3: #525c70;
  --text-4: #323a4a;
}

html, body, .main {
  font-family: 'Instrument Sans', system-ui, sans-serif !important;
  color: var(--text-1);
}

/* Preserve Streamlit's icon font on Material Symbols spans
   (the [class*="st-"] override was masking the chevron in st.status,
   making icon-ligature names like `arrow_right` leak as text). */
[class*="material-symbols"],
span[data-testid="stIconMaterial"],
span[class*="MaterialIcon"] {
  font-family: 'Material Symbols Outlined', 'Material Symbols Rounded',
               'Material Symbols Sharp', 'Material Icons' !important;
}

h1, h2, h3, h4 {
  font-family: 'Instrument Sans', sans-serif !important;
  font-weight: 700 !important;
  letter-spacing: -0.02em !important;
  color: var(--text-1);
}

code, pre, .fiq-mono {
  font-family: 'JetBrains Mono', ui-monospace, monospace !important;
}

/* Sidebar */
section[data-testid="stSidebar"] {
  background: var(--surface);
  border-right: 1px solid var(--border);
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
  letter-spacing: -0.02em;
}

/* Brand mark */
.fiq-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
}
.fiq-brand-icon {
  font-size: 28px;
  line-height: 1;
}
.fiq-brand-text {
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: var(--text-1);
}
.fiq-tagline {
  color: var(--text-3);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  margin-bottom: 14px;
}

/* Coverage stat tiles */
.fiq-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin: 12px 0 16px 0;
}
.fiq-stat {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 12px;
}
.fiq-stat-value {
  font-size: 20px;
  font-weight: 800;
  color: var(--text-1);
  letter-spacing: -0.02em;
  line-height: 1.1;
}
.fiq-stat-label {
  font-size: 11px;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-top: 2px;
}

/* Form wrapper + weight calc strip */
.fiq-weightstrip {
  display: grid;
  grid-template-columns: 1fr 1fr 1.2fr;
  gap: 16px;
  background: var(--surface-2);
  border: 1px solid var(--border-md);
  border-radius: 12px;
  padding: 14px 18px;
  margin: 8px 0 14px 0;
}
.fiq-weight-label {
  color: var(--text-3);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}
.fiq-weight-value {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text-1);
  font-family: 'JetBrains Mono', monospace !important;
}
.fiq-weight-chargeable .fiq-weight-value { color: var(--accent); }
.fiq-weight-basis {
  display: inline-block;
  padding: 2px 8px;
  font-size: 10px;
  border-radius: 999px;
  margin-left: 6px;
  border: 1px solid var(--border-md);
  color: var(--text-2);
  font-family: 'Instrument Sans', sans-serif;
  letter-spacing: 0.04em;
}

/* Submit button meta */
.fiq-submit-meta {
  font-size: 11px;
  color: var(--text-3);
  margin-top: -8px;
  letter-spacing: 0.02em;
  font-family: 'JetBrains Mono', monospace;
}

/* Rate card */
.fiq-card {
  background: var(--surface-2);
  border: 1px solid var(--border-md);
  border-radius: 14px;
  padding: 16px 18px;
  margin-bottom: 14px;
}
.fiq-card-best {
  border-color: var(--green);
  background: linear-gradient(180deg, rgba(45, 217, 139, 0.06) 0%, var(--surface-2) 100%);
}
.fiq-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}
.fiq-card-title {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.015em;
}
.fiq-pill {
  display: inline-block;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.03em;
  border: 1px solid var(--border-md);
  color: var(--text-2);
}
.fiq-pill-green { color: var(--green); border-color: var(--green); }
.fiq-pill-amber { color: var(--amber); border-color: var(--amber); }
.fiq-pill-red { color: var(--red); border-color: var(--red); }
.fiq-pill-accent { color: var(--accent); border-color: var(--accent); }

.fiq-card-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0;
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  margin: 8px 0;
}
.fiq-metric {
  padding: 10px 12px;
  background: var(--surface-3);
  border-right: 1px solid var(--border);
}
.fiq-metric:last-child { border-right: none; }
.fiq-metric-label {
  color: var(--text-3);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}
.fiq-metric-value {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-top: 2px;
  font-family: 'JetBrains Mono', monospace;
}
.fiq-metric-sub { font-size: 10px; color: var(--text-3); margin-top: 1px; }

.fiq-trustbar-track {
  width: 100%;
  height: 6px;
  border-radius: 999px;
  background: var(--surface-3);
  overflow: hidden;
  margin-top: 10px;
}
.fiq-trustbar-fill { height: 100%; }

.fiq-flags {
  margin-top: 10px;
}
.fiq-flag {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  color: var(--text-2);
  padding: 4px 0;
}
.fiq-flag-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-top: 6px;
  flex-shrink: 0;
}

.fiq-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
  font-size: 12px;
  color: var(--text-3);
}

/* Recommendation panel */
.fiq-reco {
  background: linear-gradient(180deg, rgba(45, 217, 139, 0.08) 0%, var(--surface-2) 100%);
  border: 1px solid var(--green);
  border-radius: 14px;
  padding: 16px 18px;
  margin: 14px 0;
}
.fiq-reco-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--green);
  letter-spacing: 0.03em;
  text-transform: uppercase;
  margin-bottom: 8px;
}
.fiq-reco-body {
  color: var(--text-2);
  font-size: 14px;
  line-height: 1.55;
}
.fiq-reco-body strong { color: var(--text-1); }

/* Error banner */
.fiq-error {
  background: rgba(242, 83, 83, 0.1);
  border: 1px solid var(--red);
  border-radius: 10px;
  padding: 12px 14px;
  color: var(--text-1);
  margin: 10px 0;
}

/* Section headings */
.fiq-section-head {
  color: var(--text-3);
  font-size: 11px;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  margin: 20px 0 8px 0;
}

/* Streamlit specific overrides */
.stButton > button[kind="primary"] {
  background-color: var(--accent) !important;
  color: #06070a !important;
  font-weight: 700 !important;
  border: 0 !important;
  letter-spacing: -0.01em;
}
.stButton > button[kind="primary"]:hover {
  background-color: #d8ef4e !important;
}

/* Sidebar button chips */
section[data-testid="stSidebar"] .stButton > button {
  background: var(--surface-2);
  border: 1px solid var(--border-md);
  color: var(--text-1);
  text-align: left;
  width: 100%;
  font-weight: 500;
  font-size: 13px;
}
section[data-testid="stSidebar"] .stButton > button:hover {
  border-color: var(--accent);
  color: var(--accent);
}

/* Hide Streamlit chrome we don't want */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
header[data-testid="stHeader"] { display: none; }
</style>
"""


# ---- Sidebar ----

def _render_sidebar() -> None:
    with st.sidebar:
        st.html("""
            <div class="fiq-brand">
              <div class="fiq-brand-icon">📦</div>
              <div class="fiq-brand-text">FreightIQ</div>
            </div>
            <div class="fiq-tagline">Rate intelligence</div>
            """)

        st.html("<p style='color:var(--text-2); font-size:13px; line-height:1.5;'>"
            "Enter a shipment and FreightIQ compares three freight aggregators, "
            "flags carriers that hide surcharges, and recommends the best-value "
            "route for a small-business shipper.</p>")

        st.html('<div class="fiq-section-head">Try an example</div>')
        for i, ex in enumerate(EXAMPLES):
            st.button(
                ex["label"],
                key=f"example_{i}",
                on_click=_load_example,
                args=(i,),
                use_container_width=True,
            )

        st.html('<div class="fiq-section-head">Coverage</div>')
        st.html("""
            <div class="fiq-stats">
              <div class="fiq-stat">
                <div class="fiq-stat-value">3</div>
                <div class="fiq-stat-label">Sources</div>
              </div>
              <div class="fiq-stat">
                <div class="fiq-stat-value">17</div>
                <div class="fiq-stat-label">Surcharge types</div>
              </div>
              <div class="fiq-stat">
                <div class="fiq-stat-value">4</div>
                <div class="fiq-stat-label">Agents</div>
              </div>
              <div class="fiq-stat">
                <div class="fiq-stat-value">~6s</div>
                <div class="fiq-stat-label">Analysis time</div>
              </div>
            </div>
            """)

        st.html("<p style='color:var(--text-3); font-size:11px; line-height:1.5; margin-top:20px;'>"
            "Demo mode: rates are drawn from curated fixtures, not live aggregator data. "
            "Always verify quotes with the booking site before confirming a shipment.</p>")


# ---- Weight calc strip ----

def _render_weight_strip() -> dict[str, Any]:
    weights = compute_weights(
        st.session_state["gross_weight_kg"],
        st.session_state["length_cm"],
        st.session_state["width_cm"],
        st.session_state["height_cm"],
    )
    basis_pill_text = (
        "volume weight applies"
        if weights["weight_basis"] == "volume"
        else "actual weight applies"
    )
    st.html(f"""
        <div class="fiq-weightstrip">
          <div>
            <div class="fiq-weight-label">Gross weight</div>
            <div class="fiq-weight-value">{st.session_state["gross_weight_kg"]:.1f} kg</div>
          </div>
          <div>
            <div class="fiq-weight-label">Volume weight (L×W×H÷5000)</div>
            <div class="fiq-weight-value">{weights["volume_weight_kg"]:.1f} kg</div>
          </div>
          <div class="fiq-weight-chargeable">
            <div class="fiq-weight-label">Chargeable weight
              <span class="fiq-weight-basis">{basis_pill_text}</span>
            </div>
            <div class="fiq-weight-value">{weights["chargeable_weight_kg"]:.1f} kg</div>
          </div>
        </div>
        """)
    return weights


# ---- Form ----

def _render_form() -> None:
    """Render the two-part form: live weight inputs outside st.form + batched rest inside."""

    st.html("<h2 style='margin-top:0;'>Shipment details</h2>")

    # Weight / dimensions — OUTSIDE st.form so they trigger reruns on change.
    st.html('<div class="fiq-section-head">Weight &amp; dimensions</div>')
    col_gw, col_l, col_w, col_h = st.columns([1.2, 1, 1, 1])
    with col_gw:
        st.number_input(
            "Gross weight (kg)",
            min_value=0.1,
            step=0.5,
            key="gross_weight_kg",
            format="%.1f",
        )
    with col_l:
        st.number_input("L (cm)", min_value=0.1, step=1.0, key="length_cm", format="%.1f")
    with col_w:
        st.number_input("W (cm)", min_value=0.1, step=1.0, key="width_cm", format="%.1f")
    with col_h:
        st.number_input("H (cm)", min_value=0.1, step=1.0, key="height_cm", format="%.1f")

    # Live weight calc strip (updates on every rerun).
    _render_weight_strip()

    # Batched form — cargo, route, submit.
    with st.form("shipment_form", clear_on_submit=False):
        st.html('<div class="fiq-section-head">Cargo &amp; service</div>')
        c1, c2 = st.columns(2)
        with c1:
            st.text_input(
                "Cargo type",
                key="product",
                placeholder="e.g. electronics, textiles, machinery",
            )
        with c2:
            st.selectbox(
                "Service level",
                options=["standard", "express"],
                key="urgency",
            )

        st.html('<div class="fiq-section-head">Route</div>')
        r1, r2 = st.columns(2)
        with r1:
            st.text_input("Origin", key="origin", placeholder="e.g. Delhi")
        with r2:
            st.text_input(
                "Destination",
                key="destination",
                placeholder="e.g. Rotterdam",
            )

        submitted = st.form_submit_button(
            "Run rate intelligence →",
            type="primary",
            use_container_width=True,
        )
        st.html('<div class="fiq-submit-meta">~6s analysis · ~12 LLM calls · 3 sources</div>')

    if submitted:
        _run_pipeline_and_store()


# ---- Pipeline execution ----

def _run_pipeline_and_store() -> None:
    """Validate, run pipeline with live st.status progress, store result in session."""
    errors: list[str] = []
    if not st.session_state["product"].strip():
        errors.append("Cargo type is required.")
    if not st.session_state["origin"].strip():
        errors.append("Origin is required.")
    if not st.session_state["destination"].strip():
        errors.append("Destination is required.")
    if (
        st.session_state["origin"].strip().lower()
        == st.session_state["destination"].strip().lower()
        and st.session_state["origin"].strip()
    ):
        errors.append("Origin and destination must differ.")

    if errors:
        st.session_state["error"] = " ".join(errors)
        st.session_state["result"] = None
        return

    st.session_state["error"] = None

    shipment = build_shipment_input(
        product=st.session_state["product"].strip(),
        gross_weight_kg=float(st.session_state["gross_weight_kg"]),
        length_cm=float(st.session_state["length_cm"]),
        width_cm=float(st.session_state["width_cm"]),
        height_cm=float(st.session_state["height_cm"]),
        origin=st.session_state["origin"].strip(),
        destination=st.session_state["destination"].strip(),
        urgency=st.session_state["urgency"],
    )

    with st.status("Running rate intelligence...", expanded=True) as status:
        stages = [
            ("classifying_mode", "Classifying shipment mode..."),
            ("scraping", "Fetching rates from 3 sources..."),
            ("hidden_charge", "Checking hidden charges..."),
            ("ranking", "Ranking by estimated total cost..."),
            ("writing_recommendation", "Writing recommendation..."),
        ]
        placeholders = {key: st.empty() for key, _ in stages}
        for key, label in stages:
            placeholders[key].markdown(f"◯ {label}")

        done: set[str] = set()
        current_stage = {"name": "classifying_mode"}

        def on_progress(marker: str) -> None:
            # Marker is one of: classifying_mode, scraping, hidden_charge:i/total,
            # ranking, writing_recommendation, done.
            if marker == "done":
                return
            if marker.startswith("hidden_charge:"):
                i_total = marker.split(":", 1)[1]
                placeholders["hidden_charge"].markdown(
                    f"◐ Checking hidden charges... ({i_total})"
                )
                # Mark previous stages done when we hit hidden_charge.
                for prev in ("classifying_mode", "scraping"):
                    if prev not in done:
                        done.add(prev)
                        _, lbl = next(s for s in stages if s[0] == prev)
                        placeholders[prev].markdown(f"✓ {lbl} done")
                current_stage["name"] = "hidden_charge"
                return

            # Non-hidden-charge stage transitions
            if current_stage["name"] != marker:
                # Close out the current stage as done.
                prev = current_stage["name"]
                if prev not in done:
                    done.add(prev)
                    _, lbl = next(s for s in stages if s[0] == prev)
                    placeholders[prev].markdown(f"✓ {lbl} done")
                # If hidden_charge was never entered explicitly (e.g. empty scrape),
                # bridge it as done to keep the tick ordering sensible.
                if marker == "ranking" and "hidden_charge" not in done:
                    done.add("hidden_charge")
                    placeholders["hidden_charge"].markdown("✓ Checking hidden charges... done")
                current_stage["name"] = marker
            # Mark the new current stage as active.
            label = next(lbl for key, lbl in stages if key == marker)
            placeholders[marker].markdown(f"◐ {label}")

        try:
            result = run_pipeline(shipment, on_progress=on_progress)
            # Finalise any stages still open.
            for key, lbl in stages:
                if key not in done:
                    placeholders[key].markdown(f"✓ {lbl} done")
            status.update(label="Analysis complete", state="complete")
            st.session_state["result"] = result
        except Exception as e:
            logger.exception("pipeline failed")
            status.update(label=f"Pipeline failed: {e}", state="error")
            st.session_state["error"] = f"Pipeline failed: {e}"
            st.session_state["result"] = None


# ---- Results rendering ----

def _render_rate_card(rate: dict[str, Any], rank: int) -> None:
    trust = int(rate.get("trust_score", 0))
    label = _best_value_label(rank, trust)
    band_label, band_colour, band_emoji = _trust_band(trust)
    is_best = (rank == 1 and trust >= 80)
    card_class = "fiq-card fiq-card-best" if is_best else "fiq-card"
    pill_class = {
        "Verified": "fiq-pill-green",
        "Caution": "fiq-pill-amber",
        "High risk": "fiq-pill-red",
    }.get(band_label, "")
    best_pill = (
        '<span class="fiq-pill fiq-pill-accent">BEST VALUE</span>' if is_best else ""
    )

    verified = rate.get("verified_site", False)
    verified_pill = (
        '<span class="fiq-pill fiq-pill-green">verified site</span>'
        if verified
        else '<span class="fiq-pill">unverified site</span>'
    )

    trust_colour = band_colour
    est_total = rate.get("estimated_total_usd", 0.0)
    base_price = rate.get("base_price_usd", 0.0)
    chargeable = rate.get("chargeable_weight_kg", 0.0)
    per_kg = base_price / chargeable if chargeable else 0.0
    transit_days = rate.get("transit_days", 0)

    flags = rate.get("flags") or []
    flag_html_parts = []
    for flag in flags:
        flag_html_parts.append(
            f'<div class="fiq-flag">'
            f'<span class="fiq-flag-dot" style="background:{band_colour};"></span>'
            f'<span>{_html_escape(flag)}</span>'
            f"</div>"
        )
    flags_block = (
        f'<div class="fiq-flags">{"".join(flag_html_parts)}</div>' if flags else ""
    )

    book_button_html = ""
    if trust >= 80:
        book_button_html = (
            f'<a href="{_html_escape(rate.get("booking_url", "#"))}" target="_blank" '
            f'style="background:var(--accent); color:#06070a; font-weight:700; '
            f'padding:7px 14px; border-radius:8px; text-decoration:none; '
            f'font-size:13px; letter-spacing:-0.01em;">Book now →</a>'
        )
    elif trust >= 50:
        book_button_html = (
            f'<a href="{_html_escape(rate.get("booking_url", "#"))}" target="_blank" '
            f'style="color:var(--amber); border:1px solid var(--amber); '
            f'padding:6px 13px; border-radius:8px; text-decoration:none; '
            f'font-size:13px;">Book with caution</a>'
        )
    else:
        book_button_html = (
            '<span style="color:var(--text-4); font-size:13px;">Do not book</span>'
        )

    st.html(
        f"""
        <div class="{card_class}">
          <div class="fiq-card-head">
            <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
              <span class="fiq-card-title">{_html_escape(rate.get("carrier", "?"))}</span>
              {best_pill}
              <span class="fiq-pill {pill_class}">{band_emoji} {band_label}</span>
              <span class="fiq-pill">{_html_escape(rate.get("mode", "?").replace("_", " "))}</span>
              <span class="fiq-pill">{_html_escape(rate.get("source_site", "?"))}</span>
            </div>
            <div>{verified_pill}</div>
          </div>
          <div class="fiq-card-metrics">
            <div class="fiq-metric">
              <div class="fiq-metric-label">Base rate</div>
              <div class="fiq-metric-value">${base_price:,.2f}</div>
              <div class="fiq-metric-sub">${per_kg:.2f} per kg</div>
            </div>
            <div class="fiq-metric">
              <div class="fiq-metric-label">Est. total</div>
              <div class="fiq-metric-value" style="color:{trust_colour};">
                ${est_total:,.2f}
              </div>
              <div class="fiq-metric-sub">trust-adjusted</div>
            </div>
            <div class="fiq-metric">
              <div class="fiq-metric-label">Transit</div>
              <div class="fiq-metric-value">{transit_days}d</div>
              <div class="fiq-metric-sub">door-to-door</div>
            </div>
            <div class="fiq-metric">
              <div class="fiq-metric-label">Chargeable</div>
              <div class="fiq-metric-value">{chargeable:.1f} kg</div>
              <div class="fiq-metric-sub">as quoted</div>
            </div>
          </div>
          <div>
            <div class="fiq-trustbar-track">
              <div class="fiq-trustbar-fill" style="width:{max(0, min(100, trust))}%; background:{band_colour};"></div>
            </div>
            <div style="display:flex; justify-content:space-between; color:var(--text-3); font-size:11px; margin-top:4px;">
              <span>Trust score</span>
              <span><strong style="color:{band_colour};">{trust}</strong> / 100 · {band_label}</span>
            </div>
          </div>
          {flags_block}
          <div class="fiq-card-foot">
            <span>{_html_escape(rate.get("source_site", "?"))} · {band_label.lower()}</span>
            <span>{book_button_html}</span>
          </div>
        </div>
        """
    )


def _render_recommendation_panel(text: str) -> None:
    st.html(f"""
        <div class="fiq-reco">
          <div class="fiq-reco-head">★ AI Recommendation</div>
          <div class="fiq-reco-body">{_html_escape(text)}</div>
        </div>
        """)


def _render_how_calculated(result: RecommendationResult) -> None:
    with st.expander("How this analysis was calculated"):
        st.markdown(
            f"""
**1. Chargeable weight**
```
volume_weight_kg    = (L × W × H) / 5000
chargeable_weight_kg = max(gross_weight_kg, volume_weight_kg)
```

**2. Mode classification** (deterministic thresholds)
```
< 68 kg   → courier
< 500 kg  → air_freight
≥ 500 kg  → sea_freight
```
Your shipment: **{result.get("mode", "?")}** — *{result.get("router_reason", "")}*

**3. Trust-adjusted total** (per rate)
```
factor              = (100 - trust_score) / 100 × 0.5
estimated_total_usd = base_price × (1 + factor)
```
trust 100 → +0%, trust 50 → +25%, trust 0 → +50%

**4. Ranking**
All rates sorted ascending by `estimated_total_usd`.
Source sites: {result.get("sites_succeeded", 0)} of 3 returned quotes.
Cache hit: {result.get("cache_hit", False)}.

**5. LLM pipeline**
- Groq `llama-3.3-70b-versatile` (primary) with OpenAI → Gemini fallback
- {1 + len(result.get("rates", [])) + 1} LLM calls this run
- Structured output enforced via Pydantic schemas per agent
"""
        )


def _render_results() -> None:
    err = st.session_state.get("error")
    if err:
        st.html(f'<div class="fiq-error"><strong>Can\'t run yet.</strong> {_html_escape(err)}</div>')

    result: RecommendationResult | None = st.session_state.get("result")
    if not result:
        return

    rates = result.get("rates", [])
    if not rates:
        st.html(
            f'<div class="fiq-error"><strong>No rates returned.</strong> '
            f'{_html_escape(result.get("recommendation", ""))}</div>'
        )
        return

    # Recommendation first (green panel above cards).
    if result.get("recommendation"):
        _render_recommendation_panel(result["recommendation"])

    st.html(
        f'<div class="fiq-section-head">Ranked quotes ({len(rates)})</div>'
    )
    for i, rate in enumerate(rates, 1):
        _render_rate_card(rate, i)

    # Show pipeline error summary (partial failures) below cards, non-fatal.
    if result.get("errors"):
        st.html(
            f"<p style='color:var(--amber); font-size:12px;'>"
            f"{len(result['errors'])} per-rate warning(s): "
            f"{_html_escape('; '.join(result['errors']))}</p>"
        )

    _render_how_calculated(result)


def _html_escape(s: Any) -> str:
    import html
    return html.escape(str(s))


# ---- Main entrypoint ----

def main() -> None:
    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon=PAGE_ICON,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(_CSS, unsafe_allow_html=True)
    _init_state()
    _render_sidebar()

    st.html("<h1 style='margin-bottom:0.2em;'>Freight rate intelligence</h1>"
        f"<div style='color:var(--text-2); font-size:14px; margin-bottom:22px;'>"
        f"{_html_escape(TAGLINE)}</div>")

    _render_form()
    _render_results()


if __name__ == "__main__":
    main()
