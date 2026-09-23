from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings


@override_settings(DEBUG=False, FILE_SCAN_REQUIRED=True)
class DeploymentPreflightTests(SimpleTestCase):
    def test_all_dependencies_are_checked(self):
        scanner = MagicMock()
        scanner.recv.return_value = b"PONG\0"
        scanner_context = MagicMock()
        scanner_context.__enter__.return_value = scanner
        email = MagicMock()
        email.open.return_value = True
        executor = MagicMock()
        executor.loader.graph.leaf_nodes.return_value = [("core", "0001")]
        executor.migration_plan.return_value = []
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        database = MagicMock()
        database.cursor.return_value = cursor_context

        with patch("apps.core.management.commands.deployment_preflight.connection", database), \
             patch("apps.core.management.commands.deployment_preflight.MigrationExecutor", return_value=executor), \
             patch("apps.core.management.commands.deployment_preflight.socket.create_connection", return_value=scanner_context), \
             patch("apps.core.management.commands.deployment_preflight.get_connection", return_value=email):
            output = StringIO()
            call_command("deployment_preflight", stdout=output)

        self.assertIn("Entorno de producción listo", output.getvalue())
        scanner.sendall.assert_called_once_with(b"zPING\0")
        email.open.assert_called_once()
        email.close.assert_called_once()

    def test_fails_closed_and_continues_reporting(self):
        with patch("apps.core.management.commands.deployment_preflight.Command.check_database", side_effect=OSError("sin base")), \
             patch("apps.core.management.commands.deployment_preflight.Command.check_migrations"), \
             patch("apps.core.management.commands.deployment_preflight.Command.check_private_storage"), \
             patch("apps.core.management.commands.deployment_preflight.Command.check_antivirus"), \
             patch("apps.core.management.commands.deployment_preflight.Command.check_email"):
            errors = StringIO()
            with self.assertRaises(CommandError):
                call_command("deployment_preflight", stderr=errors)

        self.assertIn("Base de datos: sin base", errors.getvalue())
