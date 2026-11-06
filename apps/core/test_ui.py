from datetime import date, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from .templatetags.ui import deadline_state, ui_lines


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
        self.assertEqual(deadline_state(self.today, self.today)["label"], "Vence hoy")

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
        self.assertContains(response, "ui-chip-correction")
