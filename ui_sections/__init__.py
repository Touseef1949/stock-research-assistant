"""UI section renderers for Stock Research Assistant.

These functions are Streamlit composition-layer functions that are kept in app.py
by design. They are deeply bound to st.* calls, session_state, and widget keys.
Extracting them would require importing Streamlit into every UI module, which
offers no architectural benefit over keeping them in the composition layer.

The spec (specs/production_test_base_refactor_spec.md) says to extract them
"if safe." After Phase 1 extraction, the risk/reward ratio for Phase 2 is poor —
all functions use st.* calls extensively and extraction would break many AppTest
tests without providing testability improvements.

Decision (2026-06-18): Skip Phase 2 extraction. Keep deep-research tab renderers
and auth/research-setup/signout renderers in app.py as the Streamlit composition
layer. This aligns with the spec's architecture principle: "Keep app.py as the
Streamlit composition layer."
"""
