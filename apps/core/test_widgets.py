from django import forms
from django.test import SimpleTestCase

from apps.core.widgets import FastSelect


class FastSelectTests(SimpleTestCase):
    choices = [
        ("", "---------"),
        (1, "Centro <Escolar> & Anexo"),
        (2, "Instituto Nacional"),
        ("Grupo", [(3, "Opción agrupada")]),
    ]

    def assert_same_html(self, value, attrs=None):
        standard = forms.Select(choices=self.choices, attrs=attrs).render("organization", value)
        fast = FastSelect(choices=self.choices, attrs=attrs).render("organization", value)
        self.assertHTMLEqual(fast, standard)

    def test_matches_standard_select_markup(self):
        self.assert_same_html(None)
        self.assert_same_html(2, attrs={"id": "id_organization", "required": True})
        self.assert_same_html(3, attrs={"disabled": True, "data-label": 'a "b"'})

    def test_escapes_labels(self):
        html = FastSelect(choices=self.choices).render("organization", None)
        self.assertIn("Centro &lt;Escolar&gt; &amp; Anexo", html)
