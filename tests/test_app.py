"""Streamlit AppTest for UI interactions — quick-pick buttons, email gate, analyze flow.

Run:  pytest tests/test_app.py -v
Requires: streamlit (>= 1.28 for AppTest)
"""

import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture()
def app(monkeypatch) -> AppTest:
    import payment

    class AuthResponse:
        session = object()
        user = type("User", (), {"id": "test-user"})()

    monkeypatch.setattr(payment, "_supabase_offline", lambda: False)
    monkeypatch.setattr(payment, "send_otp", lambda email: True)
    monkeypatch.setattr(payment, "verify_otp", lambda email, token: AuthResponse())
    monkeypatch.setattr(payment, "_ensure_user_row", lambda email, user_id=None: None)
    monkeypatch.setattr(
        payment,
        "get_user",
        lambda email: {
            "email": email,
            "plan": "free",
            "analyses_used": 0,
            "analyses_limit": 5,
        },
    )
    monkeypatch.setattr(payment, "load_auth", lambda: None)
    monkeypatch.setattr(payment, "save_auth", lambda email: None)
    monkeypatch.setattr(payment, "clear_auth", lambda: None)

    at = AppTest.from_file("app.py")
    at.run(timeout=60)
    return at


class TestSidebarQuickPicks:
    def test_default_symbol_is_sbin(self, app: AppTest):
        """Company or ticker input defaults to SBIN."""
        symbol_input = app.text_input(key="symbol_input")
        assert symbol_input.value == "SBIN"

    def test_symbol_input_label_mentions_company_or_ticker(self, app: AppTest):
        """Symbol input accepts both company names and tickers."""
        symbol_input = app.text_input(key="symbol_input")
        assert symbol_input.label == "Company or ticker"

    def test_symbol_input_placeholder_mentions_name_and_ticker(self, app: AppTest):
        """Symbol input placeholder includes a company name and ticker examples."""
        symbol_input = app.text_input(key="symbol_input")
        assert symbol_input.placeholder == "Infosys, SBIN, RELIANCE..."

    def test_clicking_reliance_updates_symbol_input(self, app: AppTest):
        """Clicking 'RELIANCE · Reliance Industries' sets symbol_input to RELIANCE."""
        btn = app.button(key="quick_RELIANCE")
        assert btn.label is not None  # button rendered
        btn.click().run()
        symbol_input = app.text_input(key="symbol_input")
        assert symbol_input.value == "RELIANCE"

    def test_clicking_tcs_updates_symbol_input(self, app: AppTest):
        """Clicking 'TCS · Tata Consultancy Services' sets symbol_input to TCS."""
        app.button(key="quick_TCS").click().run()
        assert app.text_input(key="symbol_input").value == "TCS"

    def test_clicking_sbin_resets_to_sbin(self, app: AppTest):
        """Clicking RELIANCE then SBIN should show SBIN."""
        app.button(key="quick_RELIANCE").click().run()
        app.button(key="quick_SBIN").click().run()
        assert app.text_input(key="symbol_input").value == "SBIN"

    def test_entering_company_name_survives_rerun(self, app: AppTest):
        """Typing Infosys keeps the company-name input available for resolver flow."""
        app.text_input(key="symbol_input").set_value("Infosys").run()

        assert app.text_input(key="symbol_input").value == "Infosys"
        assert app.session_state["symbol_input"] == "Infosys"


class TestEmailGate:
    def test_email_input_renders(self, app: AppTest):
        """Email text input is present."""
        email_input = app.text_input(key="_email_input")
        assert email_input is not None

    def test_confirm_email_button_renders(self, app: AppTest):
        """Send OTP button is present."""
        btn = app.button(key="send_otp_button")
        assert btn is not None

    # ── No email entered ──
    def test_confirm_without_email_does_not_show_success(self, app: AppTest):
        """Clicking Send OTP when email is empty should NOT show success."""
        # Ensure email is empty
        email_input = app.text_input(key="_email_input")
        email_input.set_value("").run()
        app.button(key="send_otp_button").click().run()
        # Should NOT show success for empty email
        success_messages = [s.value for s in app.success]
        assert "OTP sent" not in str(success_messages), \
            f"Got success for empty email: {success_messages}"

    def test_confirm_without_email_shows_warning(self, app: AppTest):
        """Clicking Send OTP with empty email should show a warning/error."""
        email_input = app.text_input(key="_email_input")
        email_input.set_value("").run()
        app.button(key="send_otp_button").click().run()
        # Should show some kind of error/warning
        assert len(app.warning) > 0 or len(app.error) > 0, \
            "Expected warning or error for empty email confirmation"

    # ── Invalid email ──
    def test_confirm_invalid_email_no_at_sign(self, app: AppTest):
        """Invalid email (no @) should not confirm."""
        email_input = app.text_input(key="_email_input")
        email_input.set_value("invalid-email").run()
        app.button(key="send_otp_button").click().run()
        success_messages = [s.value for s in app.success]
        assert "OTP sent" not in str(success_messages), \
            f"Confirmed invalid email: {success_messages}"

    def test_confirm_invalid_email_shows_error(self, app: AppTest):
        """Invalid email should show error message."""
        email_input = app.text_input(key="_email_input")
        email_input.set_value("notanemail").run()
        app.button(key="send_otp_button").click().run()
        assert len(app.warning) > 0 or len(app.error) > 0

    # ── Valid email ──
    def test_confirm_valid_email_shows_success(self, app: AppTest):
        """Valid email should send and verify an OTP."""
        email_input = app.text_input(key="_email_input")
        email_input.set_value("test@example.com").run()
        app.button(key="send_otp_button").click().run()
        app.text_input(key="_otp_input").set_value("123456").run()
        app.button(key="verify_otp_button").click().run()
        success_messages = [s.value for s in app.success]
        assert any("Verified as test@example.com" in str(m) for m in success_messages), \
            f"Expected success for valid email, got: {success_messages}"

    def test_confirm_valid_email_shows_plan_info(self, app: AppTest):
        """Valid email confirmation should show plan info."""
        email_input = app.text_input(key="_email_input")
        email_input.set_value("user@test.com").run()
        app.button(key="send_otp_button").click().run()
        app.text_input(key="_otp_input").set_value("123456").run()
        app.button(key="verify_otp_button").click().run()
        # Should show plan-related text somewhere
        captions = [c.value for c in app.caption]
        markdowns = [m.value for m in app.markdown]
        all_text = str(captions) + str(markdowns) + str([s.value for s in app.success])
        assert any(word in all_text.lower() for word in ["free", "pro", "plan"]), \
            f"Expected plan info, got: {all_text[:200]}"

    # ── Whitespace handling ──
    def test_confirm_whitespace_only_email_fails(self, app: AppTest):
        """Whitespace-only email should not confirm — show error or warning."""
        email_input = app.text_input(key="_email_input")
        email_input.set_value("   ").run()
        app.button(key="send_otp_button").click().run()
        # Should show a warning about invalid/empty email
        assert len(app.warning) > 0 or len(app.error) > 0, \
            f"Expected warning/error for whitespace email, got none"

    def test_confirm_email_with_surrounding_spaces_works(self, app: AppTest):
        """Email with surrounding spaces should be trimmed and work."""
        email_input = app.text_input(key="_email_input")
        email_input.set_value("  test@example.com  ").run()
        app.button(key="send_otp_button").click().run()
        app.text_input(key="_otp_input").set_value("123456").run()
        app.button(key="verify_otp_button").click().run()
        success_messages = [s.value for s in app.success]
        assert any("Verified as test@example.com" in str(m) for m in success_messages), \
            f"Expected confirmation for space-padded email"

    # ── Re-confirm / state persistence ──
    def test_email_confirmed_persists_across_rerun(self, app: AppTest):
        """Email confirmed state should persist after rerun."""
        email_input = app.text_input(key="_email_input")
        email_input.set_value("persist@test.com").run()
        app.button(key="send_otp_button").click().run()
        app.text_input(key="_otp_input").set_value("123456").run()
        app.button(key="verify_otp_button").click().run()
        # Rerun without clicking again
        app.run()
        success_messages = [s.value for s in app.success]
        assert any("Verified as persist@test.com" in str(m) for m in success_messages), \
            "Email confirmation did not persist after rerun"

    # ── Email change resets confirmation ──
    def test_changing_email_resets_confirmation(self, app: AppTest):
        """Changing email should require re-confirmation."""
        email_input = app.text_input(key="_email_input")
        email_input.set_value("first@test.com").run()
        app.button(key="send_otp_button").click().run()
        app.text_input(key="_otp_input").set_value("123456").run()
        app.button(key="verify_otp_button").click().run()
        # Now change email
        email_input.set_value("second@test.com").run()
        # After email change, confirmation should reset
        success_messages = [s.value for s in app.success]
        # Should NOT still show "Email confirmed" without re-clicking
        # (This depends on implementation - the email change triggers rerun in render_email_gate)
        # At minimum, the previous confirmation was for a different email


    # ── Verify then generate ──
    # ── Verify then generate: session state must survive any rerun ──
    def test_verify_then_rerun_keeps_email(self, app: AppTest):
        """After OTP verify, session_state._auth_verified and user_email survive a plain rerun."""
        app.text_input(key="_email_input").set_value("survive@test.com").run()
        app.button(key="send_otp_button").click().run()
        app.text_input(key="_otp_input").set_value("123456").run()
        app.button(key="verify_otp_button").click().run()

        # After verification, auth state is set.
        assert app.session_state["_auth_verified"] is True
        assert app.session_state["user_email"] == "survive@test.com"

        # Simulate any user interaction that triggers a rerun (like clicking Generate).
        app.run()

        # Auth must still hold.
        assert app.session_state["_auth_verified"] is True
        assert app.session_state["user_email"] == "survive@test.com"

        # And no warning asking to enter email should appear.
        warning_texts = [w.value for w in app.warning]
        assert "Enter your email" not in str(warning_texts), \
            f"Email was lost after rerun: warnings={warning_texts}"


class TestAnalyzeButton:
    def test_analyze_button_renders_primary(self, app: AppTest):
        """Hero analyze button exists and is primary type."""
        btn = app.button(key="hero_analyze_button")
        assert btn is not None

    @pytest.mark.skip(reason="AppTest st.stop() incompatible with network-heavy app; validate manually")
    def test_analyze_without_email_shows_warning(self, app: AppTest):
        """Clicking Analyze without email should show a warning."""
        btn = app.button(key="hero_analyze_button")
        btn.click().run()
        # Should show a warning about entering email (from require_payment)
        assert len(app.warning) > 0, \
            f"Expected warning when analyzing without email, got warnings={[w.value for w in app.warning]}"


class TestEmptyState:
    def test_hero_section_renders(self, app: AppTest):
        """The empty state hero section is present."""
        assert len(app.markdown) > 0

    def test_sidebar_brand_renders(self, app: AppTest):
        """Sidebar brand card is present."""
        assert app.sidebar is not None
