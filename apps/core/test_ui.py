from datetime import date, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from .templatetags.ui import STATUS_STYLES, TONES, deadline_state, severity_style, status_style, ui_lines, ui_wait_chip


class DeadlineStateTests(TestCase):
    def setUp(self):
        self.today = date(2026, 11, 6)
        translation.activate("es")

    def tearDown(self):
        translation.deactivate()

    def test_overdue_deadline_is_written_in_words(self):
        state = deadline_state(date(2026, 10, 4), self.today)
        self.assertEqual(state["tone"], "danger")
        self.assertEqual(state["label"], "Venció el 4 oct")

    def test_deadline_today(self):
        state = deadline_state(self.today, self.today)
        self.assertEqual(state["label"], "Vence hoy")
        self.assertEqual(state["tone"], "warning", "El rojo queda para lo que ya venció")

    def test_deadline_within_a_week_warns(self):
        state = deadline_state(self.today + timedelta(days=3), self.today)
        self.assertEqual(state["tone"], "warning")
        self.assertEqual(state["label"], "Vence el 9 nov")

    def test_distant_deadline_is_neutral_and_shows_other_year(self):
        state = deadline_state(date(2027, 1, 12), self.today)
        self.assertEqual(state["tone"], "neutral")
        self.assertEqual(state["label"], "Vence el 12 ene 2027")

    def test_missing_deadline(self):
        self.assertIsNone(deadline_state(None, self.today))

    def test_uses_application_date_by_default(self):
        state = deadline_state(timezone.localdate())
        self.assertEqual(state["label"], "Vence hoy")


class LinesFilterTests(TestCase):
    def test_splits_requirements_and_strips_bullets(self):
        self.assertEqual(
            ui_lines("- Comprobantes de depósito.\n\n• Estado de cuenta.\n"),
            ["Comprobantes de depósito.", "Estado de cuenta."],
        )

    def test_empty_value(self):
        self.assertEqual(ui_lines(""), [])


class UiReferencePageTests(TestCase):
    def test_hidden_outside_development(self):
        self.assertEqual(self.client.get(reverse("ui_reference")).status_code, 404)

    @override_settings(DEBUG=True)
    def test_available_in_development(self):
        response = self.client.get(reverse("ui_reference"))
        self.assertContains(response, "Componentes")
        self.assertContains(response, "ui-chip-warning")
        self.assertContains(response, "ui-severity")
        self.assertNotContains(response, "ui-chip-correction")


class StatusSystemTests(TestCase):
    """Un solo código de estados: cada valor del modelo tiene tono e ícono, y la etiqueta es la del modelo."""

    def test_every_model_status_has_a_style(self):
        from apps.accounts.models import TechnicalSupportRequest
        from apps.audits.models import AuditCase, AuditDocument, AuditInquiry, CaseDecision, Recommendation, Review

        families = {
            "case": AuditCase.Status,
            "recommendation": Recommendation.Status,
            "inquiry": AuditInquiry.Status,
            "support": TechnicalSupportRequest.Status,
            "decision": CaseDecision.Status,
            "document": AuditDocument.Status,
            "review_outcome": Review.Outcome,
        }
        for family, choices in families.items():
            self.assertEqual(set(STATUS_STYLES[family]), set(choices.values), family)
            for value, label in choices.choices:
                style = status_style(family, value)
                self.assertIn(style["tone"], TONES)
                self.assertEqual(style["label"], label)

    def test_only_four_colors_and_neutral(self):
        tones = {tone for styles in STATUS_STYLES.values() for tone, _icon in styles.values()}
        self.assertLessEqual(tones, set(TONES))

    def test_green_only_for_final_positive_results(self):
        self.assertEqual(status_style("case", "pending_closure")["tone"], "info")
        self.assertEqual(status_style("recommendation", "partial")["tone"], "warning")
        self.assertEqual(status_style("case", "closed")["tone"], "success")

    def test_returned_and_correction_share_one_meaning(self):
        self.assertEqual(status_style("decision", "returned")["tone"], "warning")
        self.assertEqual(status_style("recommendation", "correction_required")["tone"], "warning")

    def test_severity_scale_is_shared_by_risk_and_attention(self):
        for risk, attention in (("critical", "immediate"), ("high", "high"), ("medium", "followup"), ("low", "stable")):
            self.assertEqual(severity_style("risk", risk, "")["tone"], severity_style("attention", attention, "")["tone"])
        self.assertEqual(severity_style("risk", "critical", "", muted=True)["tone"], "neutral")

    def test_waiting_decision_escalates_after_a_week(self):
        now = timezone.now()
        self.assertEqual(ui_wait_chip(now - timedelta(days=2), now)["tone"], "info")
        self.assertEqual(ui_wait_chip(now - timedelta(days=9), now)["tone"], "warning")
