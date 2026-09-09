import re
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.audits.models import ActivityLog
from apps.institutions.models import Organization
from .activation import activation_token_generator
from .models import User


@override_settings(PUBLIC_BASE_URL="https://auditoria.example", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CenterActivationTests(TestCase):
    def setUp(self):
        self.center = Organization.objects.create(
            code="00123", name="Centro de prueba", kind="educational_center",
            email="00123@example.edu.sv",
        )
        self.director = User.objects.create_user(
            username="directora", role="audit_manager", password="DirectoraSegura!2026",
            must_change_password=False,
        )
        self.client.force_login(self.director)
        self.url = reverse("director_activate_educational_center", args=[self.center.pk])
        self.visitor = Client()

    def invite(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        account = User.objects.get(organization=self.center)
        path = re.search(r"https://auditoria.example(/activar-cuenta/\S+)", mail.outbox[-1].body).group(1)
        return account, path

    def password_form(self, path):
        response = self.visitor.get(path)
        self.assertEqual(response.status_code, 302)
        form_path = response.url
        self.assertNotIn(path.split("/")[-2], form_path)
        self.assertContains(self.visitor.get(form_path), "Establecer contraseña")
        return form_path

    def test_single_use_link_activates_only_after_a_valid_password(self):
        account, path = self.invite()
        self.assertEqual(mail.outbox[0].to, [self.center.email])
        self.assertEqual(account.username, "00123")
        self.assertFalse(account.is_active)
        self.assertFalse(account.has_usable_password())
        self.assertFalse(self.visitor.login(username="00123", password="00123"))
        form_path = self.password_form(path)
        self.assertContains(self.visitor.post(form_path, {
            "new_password1": "00123", "new_password2": "00123",
        }), "demasiado corta")
        account.refresh_from_db()
        self.assertFalse(account.is_active)
        password = "AccesoEscolarSeguro!2026"
        self.assertRedirects(self.visitor.post(form_path, {
            "new_password1": password, "new_password2": password,
        }), reverse("login"))
        account.refresh_from_db()
        self.assertTrue(account.is_active)
        self.assertFalse(account.must_change_password)
        self.assertIsNone(account.activation_requested_at)
        self.assertTrue(self.visitor.login(username="00123", password=password))
        self.visitor.logout()
        self.assertContains(self.visitor.get(path), "Enlace no disponible")
        self.assertContains(self.visitor.post(form_path, {
            "new_password1": "OtraClaveSegura!2026", "new_password2": "OtraClaveSegura!2026"
        }), "Enlace no disponible")
        self.assertEqual(ActivityLog.objects.filter(action="educational_center_activated").count(), 1)

    def test_resend_invalidates_old_link_and_reuses_account(self):
        first, old_path = self.invite()
        old_form = self.password_form(old_path)
        second, new_path = self.invite()
        self.assertEqual(first.pk, second.pk)
        self.assertNotEqual(old_path, new_path)
        self.assertContains(self.visitor.get(old_path), "Enlace no disponible")
        self.assertContains(self.visitor.get(old_form), "Enlace no disponible")
        self.password_form(new_path)

    def test_expired_link_does_not_enable_access(self):
        account, path = self.invite()
        future = activation_token_generator._now() + timedelta(hours=25)
        with patch.object(activation_token_generator, "_now", return_value=future):
            self.assertContains(self.visitor.get(path), "Enlace no disponible")
        account.refresh_from_db()
        self.assertFalse(account.is_active)

    def test_email_change_or_center_suspension_revokes_link(self):
        account, path = self.invite()
        self.center.email = "otro@example.edu.sv"
        self.center.save()
        self.assertContains(self.visitor.get(path), "Enlace no disponible")
        self.center.email = account.email
        self.center.is_active = False
        self.center.save()
        self.assertContains(self.visitor.get(path), "Enlace no disponible")

    def test_missing_or_conflicting_email_prevents_invitation(self):
        self.center.email = ""
        self.center.save()
        self.client.post(self.url)
        self.assertFalse(User.objects.filter(organization=self.center).exists())
        self.center.email = "compartido@example.edu.sv"
        self.center.save()
        Organization.objects.create(code="other", name="Otro", kind="educational_center", email=self.center.email)
        self.client.post(self.url)
        self.assertFalse(User.objects.filter(organization=self.center).exists())

    def test_mail_failure_rolls_back_account_and_keeps_previous_invitation(self):
        with patch("apps.accounts.activation.send_mail", side_effect=OSError("SMTP unavailable")):
            self.client.post(self.url)
        self.assertFalse(User.objects.filter(organization=self.center).exists())
        account, path = self.invite()
        with patch("apps.accounts.activation.send_mail", side_effect=OSError("SMTP unavailable")):
            self.client.post(self.url)
        self.password_form(path)
        self.assertEqual(ActivityLog.objects.filter(action="educational_center_invited").count(), 1)

    def test_active_account_is_not_reset_by_invitation(self):
        account = User.objects.create_user(username="00123", organization=self.center,
            role="institution", email=self.center.email, password="ClaveExistente!2026")
        old_password = account.password
        self.client.post(self.url)
        account.refresh_from_db()
        self.assertEqual(account.password, old_password)
        self.assertTrue(account.is_active)
        self.assertEqual(len(mail.outbox), 0)

    def test_permissions_get_and_forged_links(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.visitor.post(self.url).status_code, 403)
        self.assertContains(self.visitor.get("/activar-cuenta/invalid/falso/"), "Enlace no disponible")
        self.director.role = "auditor"
        self.director.save()
        self.assertEqual(self.client.post(self.url).status_code, 403)

    @override_settings(DEBUG=False, PUBLIC_BASE_URL="http://inseguro.example")
    def test_production_requires_https_origin(self):
        self.client.post(self.url)
        self.assertFalse(User.objects.filter(organization=self.center).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_conflicting_username_does_not_get_a_suffix_or_overwrite_account(self):
        other = User.objects.create_user(username="00123", role="auditor")
        self.client.post(self.url)
        self.assertFalse(User.objects.filter(organization=self.center).exists())
        other.refresh_from_db()
        self.assertEqual(other.role, "auditor")
