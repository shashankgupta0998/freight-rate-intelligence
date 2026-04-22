"""Phase 4 smoke tests — verify app.py imports cleanly and
build_shipment_input emits the exact CLAUDE.md ShipmentInput schema.

No LLM calls. No Streamlit runtime — we import the helper functions only.
AppTest-based full-page loading is deferred to a future Phase-5 test.
"""
from __future__ import annotations


REQUIRED_SHIPMENT_KEYS = {
    "product",
    "gross_weight_kg",
    "length_cm",
    "width_cm",
    "height_cm",
    "volume_weight_kg",
    "chargeable_weight_kg",
    "weight_basis",
    "origin",
    "destination",
    "urgency",
}


def test_app_module_importable():
    """`import app` must not raise and must expose the two public helpers."""
    import app
    assert hasattr(app, "build_shipment_input")
    assert callable(app.build_shipment_input)
    assert hasattr(app, "compute_weights")
    assert callable(app.compute_weights)


def test_compute_weights_volume_dominant():
    """Volume weight > gross weight -> chargeable is volume, basis='volume'."""
    from app import compute_weights

    # 100*100*100 / 5000 = 200.0 > 50 gross
    out = compute_weights(50.0, 100.0, 100.0, 100.0)
    assert out["volume_weight_kg"] == 200.0
    assert out["chargeable_weight_kg"] == 200.0
    assert out["weight_basis"] == "volume"


def test_compute_weights_gross_dominant():
    """Gross weight > volume weight -> chargeable is gross, basis='gross'."""
    from app import compute_weights

    # 40*30*20 / 5000 = 4.8 < 12 gross
    out = compute_weights(12.0, 40.0, 30.0, 20.0)
    assert out["volume_weight_kg"] == 4.8
    assert out["chargeable_weight_kg"] == 12.0
    assert out["weight_basis"] == "gross"


def test_compute_weights_equal():
    """Equal gross and volume weights -> basis='gross' (ties go to actual)."""
    from app import compute_weights

    # 100*100*100 / 5000 = 200 == 200 gross
    out = compute_weights(200.0, 100.0, 100.0, 100.0)
    assert out["volume_weight_kg"] == 200.0
    assert out["chargeable_weight_kg"] == 200.0
    assert out["weight_basis"] == "gross"


def test_build_shipment_input_schema_matches_claude_md():
    """build_shipment_input must emit every key in the CLAUDE.md ShipmentInput contract."""
    from app import build_shipment_input

    shipment = build_shipment_input(
        product="electronics",
        gross_weight_kg=12.0,
        length_cm=40.0,
        width_cm=30.0,
        height_cm=20.0,
        origin="Delhi",
        destination="Rotterdam",
        urgency="standard",
    )

    assert set(shipment.keys()) == REQUIRED_SHIPMENT_KEYS, (
        f"shipment keys diverge from CLAUDE.md contract. "
        f"missing={REQUIRED_SHIPMENT_KEYS - set(shipment.keys())}, "
        f"extra={set(shipment.keys()) - REQUIRED_SHIPMENT_KEYS}"
    )
    assert shipment["product"] == "electronics"
    assert shipment["gross_weight_kg"] == 12.0
    assert shipment["volume_weight_kg"] == 4.8
    assert shipment["chargeable_weight_kg"] == 12.0
    assert shipment["weight_basis"] == "gross"
    assert shipment["origin"] == "Delhi"
    assert shipment["destination"] == "Rotterdam"
    assert shipment["urgency"] == "standard"


def test_app_imports_run_pipeline():
    """app.py must import run_pipeline from pipeline (not re-implement it)."""
    import inspect
    import app

    assert hasattr(app, "run_pipeline")
    # sanity: the imported function is from the pipeline module
    assert inspect.getmodule(app.run_pipeline).__name__ == "pipeline"


def test_pipeline_accepts_on_progress_callback():
    """pipeline.run_pipeline must accept the on_progress keyword for UI integration."""
    import inspect
    from pipeline import run_pipeline

    sig = inspect.signature(run_pipeline)
    assert "on_progress" in sig.parameters
    param = sig.parameters["on_progress"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY
    assert param.default is None
