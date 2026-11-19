import shutil
import tempfile
from io import BytesIO

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.audits.models import ActivityLog
from apps.institutions.models import Organization

from .models import User
from .security import describe_device

PHONE_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; SM-A146M) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"
)


def image_upload(name="foto.png", fmt="PNG", size=(800, 600), color=(200, 30, 30)):
    buffer = BytesIO()
    image = Image.new("RGB", size, color)
    if fmt == "JPEG":
        exif = Image.Exif()
        exif[0x010F] = "Fabricante"  # Make
        image.save(buffer, format=fmt, exif=exif)
    else:
        image.save(buffer, format=fmt)
    content_type = "image/png" if fmt == "PNG" else "image/jpeg"
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


class ProfileTestBase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_root = tempfile.mkdtemp()
        cls.media_override = override_settings(MEDIA_ROOT=cls.media_root)
        cls.media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls.media_override.disable()
        shutil.rmtree(cls.media_root, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.center = Organization.objects.create(
            code="10001", name="Centro Escolar Uno", kind="educational_center",
            department="San Salvador", district="San Salvador Centro",
        )
        self.other_center = Organization.objects.create(
            code="10002", name="Centro Escolar Dos", kind="educational_center",
        )
        self.institution = User.objects.create_user(
            username="10001", password="Clave-Segura-2026", role=User.Role.INSTITUTION,
            organization=self.center, first_name="Ana", last_name="López", must_change_password=False,
        )
        self.colleague = User.objects.create_user(
            username="10001-b", password="Clave-Segura-2026", role=User.Role.INSTITUTION,
            organization=self.center, must_change_password=False,
        )
        self.other_institution = User.objects.create_user(
            username="10002", password="Clave-Segura-2026", role=User.Role.INSTITUTION,
            organization=self.other_center, must_change_password=False,
        )
        self.auditor = User.objects.create_user(
            username="auditor", password="Clave-Segura-2026", role=User.Role.AUDITOR,
            first_name="Luis", last_name="Martínez", must_change_password=False,
        )
        self.director = User.objects.create_user(
            username="directora", password="Clave-Segura-2026", role=User.Role.AUDIT_MANAGER,
            must_change_password=False,
        )
        self.technical = User.objects.create_user(
            username="tecnica", password="Clave-Segura-2026", role=User.Role.TECHNICAL_ADMIN,
            must_change_password=False,
        )


class ProfilePageTests(ProfileTestBase):
    def test_each_role_sees_its_own_summary(self):
        expected = {
            self.institution: "Su centro",
            self.auditor: "Su trabajo",
            self.director: "Dirección",
            self.technical: "Administración técnica",
        }
        for user, title in expected.items():
            with self.subTest(role=user.role):
                self.client.force_login(user)
                response = self.client.get(reverse("account_profile"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, title)
                self.assertContains(response, "Datos personales")
                self.assertContains(response, "Seguridad")

    def test_institution_summary_shows_center_data(self):
        self.client.force_login(self.institution)
        response = self.client.get(reverse("account_profile"))
        self.assertContains(response, "10001")
        self.assertContains(response, "San Salvador Centro")
        self.assertContains(response, reverse("institution_technical_support"))

    def test_personal_data_is_saved_and_logged(self):
        self.client.force_login(self.auditor)
        response = self.client.post(reverse("account_profile"), {
            "section": "personal",
            "personal-first_name": "Luis Alberto",
            "personal-last_name": "Martínez",
            "personal-job_title": "Auditor II",
            "personal-phone": "+503 7000-0000",
        })
        self.assertRedirects(response, f"{reverse('account_profile')}#datos")
        self.auditor.refresh_from_db()
        self.assertEqual(self.auditor.first_name, "Luis Alberto")
        self.assertEqual(self.auditor.phone, "+503 7000-0000")
        log = ActivityLog.objects.get(action="profile_updated")
        self.assertEqual(set(log.details["fields"]), {"first_name", "job_title", "phone"})

    def test_username_and_email_cannot_be_changed_from_profile(self):
        self.client.force_login(self.institution)
        self.client.post(reverse("account_profile"), {
            "section": "personal", "personal-first_name": "Ana",
            "personal-username": "otro", "personal-email": "otro@example.com",
        })
        self.institution.refresh_from_db()
        self.assertEqual(self.institution.username, "10001")
        self.assertEqual(self.institution.email, "")

    def test_invalid_phone_is_rejected(self):
        self.client.force_login(self.auditor)
        response = self.client.post(reverse("account_profile"), {
            "section": "personal", "personal-first_name": "Luis", "personal-phone": "llámeme",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Escriba un teléfono válido")
        self.auditor.refresh_from_db()
        self.assertEqual(self.auditor.phone, "")

    def test_large_text_preference_marks_every_page(self):
        self.client.force_login(self.institution)
        self.client.post(reverse("account_profile"), {"section": "preferences", "preferences-text_size": "large"})
        self.institution.refresh_from_db()
        self.assertEqual(self.institution.text_size, User.TextSize.LARGE)
        response = self.client.get(reverse("dashboard"), follow=True)
        self.assertContains(response, 'data-text-size="large"')

    def test_profile_requires_login(self):
        response = self.client.get(reverse("account_profile"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])


class AvatarTests(ProfileTestBase):
    def upload(self, user, file):
        self.client.force_login(user)
        return self.client.post(reverse("account_profile"), {"section": "avatar", "avatar-photo": file})

    def test_upload_is_reencoded_as_square_jpeg_without_metadata(self):
        response = self.upload(self.institution, image_upload("foto.jpg", fmt="JPEG"))
        self.assertRedirects(response, reverse("account_profile"))
        self.institution.refresh_from_db()
        self.assertTrue(self.institution.avatar.name.startswith("perfiles/"))
        self.assertIsNotNone(self.institution.avatar_updated_at)
        with self.institution.avatar.open("rb") as stored, Image.open(stored) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (384, 384))
            self.assertEqual(len(image.getexif()), 0)
        self.assertTrue(ActivityLog.objects.filter(action="profile_photo_updated", actor=self.institution).exists())

    def test_replacing_and_removing_delete_the_previous_file(self):
        self.upload(self.institution, image_upload())
        self.institution.refresh_from_db()
        first = self.institution.avatar.name
        self.upload(self.institution, image_upload(color=(0, 0, 200)))
        self.institution.refresh_from_db()
        second = self.institution.avatar.name
        self.assertNotEqual(first, second)
        self.assertFalse(default_storage.exists(first))
        self.client.post(reverse("account_profile"), {"section": "avatar_remove"})
        self.institution.refresh_from_db()
        self.assertFalse(self.institution.avatar)
        self.assertFalse(default_storage.exists(second))
        self.assertTrue(ActivityLog.objects.filter(action="profile_photo_removed").exists())

    def test_files_that_are_not_images_are_rejected(self):
        fake = SimpleUploadedFile("foto.png", b"esto no es una imagen", content_type="image/png")
        response = self.upload(self.institution, fake)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No se pudo leer la foto")
        pdf = SimpleUploadedFile("foto.pdf", b"%PDF-1.4", content_type="application/pdf")
        response = self.upload(self.institution, pdf)
        self.assertContains(response, "Use una foto JPG o PNG")
        self.institution.refresh_from_db()
        self.assertFalse(self.institution.avatar)

    def test_extension_must_match_real_format(self):
        disguised = image_upload("foto.png", fmt="GIF")
        response = self.upload(self.institution, disguised)
        self.assertContains(response, "Use una foto JPG o PNG")

    def test_avatar_access_follows_organization_scope(self):
        self.upload(self.institution, image_upload())
        self.upload(self.auditor, image_upload())
        institution_photo = reverse("user_avatar", args=[self.institution.pk])
        auditor_photo = reverse("user_avatar", args=[self.auditor.pk])
        cases = [
            (self.institution, institution_photo, 200),
            (self.colleague, institution_photo, 200),
            (self.other_institution, institution_photo, 403),
            (self.auditor, institution_photo, 200),
            (self.director, institution_photo, 200),
            (self.technical, auditor_photo, 200),
            # Las instituciones ven a Auditoría sin nombre ni foto.
            (self.institution, auditor_photo, 403),
        ]
        for viewer, url, status in cases:
            with self.subTest(viewer=viewer.username, url=url):
                client = Client()
                client.force_login(viewer)
                response = client.get(url)
                self.assertEqual(response.status_code, status)
                if status == 200:
                    self.assertEqual(response["Content-Type"], "image/jpeg")
                    self.assertIn("private", response["Cache-Control"])
                    self.assertTrue(b"".join(response.streaming_content))

    def test_anonymous_users_cannot_fetch_photos(self):
        self.upload(self.institution, image_upload())
        self.client.logout()
        response = self.client.get(reverse("user_avatar", args=[self.institution.pk]))
        self.assertEqual(response.status_code, 302)

    def test_inquiry_thread_hides_auditor_photo_from_institutions(self):
        from apps.core.templatetags.ui import ui_avatar

        self.upload(self.auditor, image_upload())
        self.auditor.refresh_from_db()
        self.assertEqual(ui_avatar({"user": self.institution}, self.auditor)["url"], "")
        self.assertTrue(ui_avatar({"user": self.director}, self.auditor)["url"])

    def test_initials_are_shown_without_photo(self):
        self.client.force_login(self.institution)
        response = self.client.get(reverse("account_profile"))
        self.assertContains(response, ">AL</span>")


class SecurityPanelTests(ProfileTestBase):
    def test_set_password_records_the_change_date(self):
        self.auditor.password_changed_at = None
        self.auditor.set_password("Otra-Clave-Segura-2026")
        self.assertIsNotNone(self.auditor.password_changed_at)

    def test_login_is_logged_with_a_short_device_name(self):
        client = Client(HTTP_USER_AGENT=PHONE_AGENT)
        client.post(reverse("login"), {"username": "auditor", "password": "Clave-Segura-2026"})
        log = ActivityLog.objects.get(action="login", actor=self.auditor)
        self.assertEqual(log.details, {"device": "Chrome en teléfono Android"})

    def test_device_names(self):
        self.assertEqual(describe_device(""), "Navegador")
        self.assertEqual(
            describe_device("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36 Edg/130.0"),
            "Edge en Windows",
        )
        self.assertEqual(
            describe_device("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"),
            "Safari en iPhone",
        )

    def test_close_other_sessions_keeps_the_current_one(self):
        phone = Client()
        phone.force_login(self.auditor)
        computer = Client()
        computer.force_login(self.auditor)
        response = computer.get(reverse("account_profile"))
        self.assertContains(response, "2 dispositivos")
        self.assertContains(response, "Cerrar las demás sesiones")
        computer.post(reverse("account_close_other_sessions"))
        self.assertEqual(computer.get(reverse("account_profile")).status_code, 200)
        self.assertEqual(phone.get(reverse("account_profile")).status_code, 302)
        log = ActivityLog.objects.get(action="other_sessions_closed")
        self.assertEqual(log.details, {"closed": 1})

    def test_close_other_sessions_requires_post(self):
        self.client.force_login(self.auditor)
        self.assertEqual(self.client.get(reverse("account_close_other_sessions")).status_code, 405)

    def test_previous_login_is_shown(self):
        for _ in range(2):
            Client(HTTP_USER_AGENT=PHONE_AGENT).post(
                reverse("login"), {"username": "auditor", "password": "Clave-Segura-2026"}
            )
        self.client.force_login(self.auditor)
        response = self.client.get(reverse("account_profile"))
        self.assertContains(response, "Chrome en teléfono Android")
        self.assertContains(response, "Ver ingresos recientes")


class AvatarPlacementTests(ProfileTestBase):
    def test_pages_that_list_people_render_with_avatars(self):
        Client(HTTP_USER_AGENT=PHONE_AGENT).post(
            reverse("login"), {"username": "auditor", "password": "Clave-Segura-2026"}
        )
        pages = [
            (self.technical, reverse("technical_activity_log")),
            (self.technical, reverse("technical_users")),
            (self.technical, reverse("technical_user_detail", args=[self.auditor.pk])),
            (self.director, reverse("director_auditors")),
            (self.director, reverse("director_auditor_detail", args=[self.auditor.pk])),
            (self.director, reverse("director_activity")),
        ]
        for viewer, url in pages:
            with self.subTest(url=url):
                client = Client()
                client.force_login(viewer)
                response = client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "ui-avatar ")
