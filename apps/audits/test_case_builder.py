from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.institutions.models import Organization

from .models import ActivityLog, AuditCase, BusinessDayHoliday, Finding, Recommendation
from .services import add_business_days, recommendation_deadline_shortcuts
from .snippets import learned_evidence_snippets


class CaseBuilderAssistanceTests(TestCase):
    """Ayudas del formulario de hallazgos y recomendaciones para el personal auditor."""

    def setUp(self):
        self.center = Organization.objects.create(
            code="10754", name="Centro Uno", kind=Organization.Kind.EDUCATIONAL_CENTER
        )
        audit_unit = Organization.objects.create(
            code="DAI", name="Auditoría Interna", kind=Organization.Kind.MINISTRY_UNIT
        )
        self.auditor = User.objects.create_user(
            username="auditor",
            role=User.Role.AUDITOR,
            organization=audit_unit,
            must_change_password=False,
        )
        self.auditor.assigned_organizations.add(self.center)
        self.other_auditor = User.objects.create_user(
            username="otro-auditor",
            role=User.Role.AUDITOR,
            organization=audit_unit,
            must_change_password=False,
        )
        # Viernes 13 de noviembre de 2026.
        self.case = AuditCase.objects.create(
            reference="IA-BUILDER-001",
            title="Fondos de funcionamiento",
            audited_organization=self.center,
            status=AuditCase.Status.DRAFT,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
            report_date=date(2026, 11, 13),
            response_deadline=date(2026, 12, 18),
        )
        self.finding = Finding.objects.create(
            case=self.case,
            number=1,
            title="Falta de conciliaciones",
            risk_level=Finding.RiskLevel.HIGH,
            condition="No se elaboraron conciliaciones.",
        )
        self.recommendation = Recommendation.objects.create(
            finding=self.finding,
            number=1,
            text="Elabore las conciliaciones mensuales.",
            responsible_organization=self.center,
            deadline=date(2026, 12, 18),
        )
        self.client.force_login(self.auditor)

    def finding_payload(self, **overrides):
        payload = {
            "number": 2,
            "title": "Inventario desactualizado",
            "risk_level": Finding.RiskLevel.MEDIUM,
            "condition": "El inventario no incluye las compras de 2026.",
            "criteria": "El instructivo exige actualizar el inventario.",
            "cause": "No se asignó un responsable.",
            "effect": "Bienes sin control.",
        }
        payload.update(overrides)
        return payload

    def recommendation_payload(self, **overrides):
        payload = {
            "number": 2,
            "text": "Designe al responsable del inventario.",
            "responsible_organization": self.center.pk,
            "deadline": "2026-12-18",
            "evidence_requirements": "Acta de designación.",
        }
        payload.update(overrides)
        return payload

    def test_finding_form_shows_guiding_questions_and_examples(self):
        page = self.client.get(reverse("finding_create", args=[self.case.pk]))
        self.assertContains(page, "¿Qué se encontró?")
        self.assertContains(page, "¿Qué norma, disposición o procedimiento")
        self.assertContains(page, "Ver ejemplo", count=5)
        self.assertContains(page, "Guardar y agregar recomendación")

    def test_save_finding_and_continue_with_its_first_recommendation(self):
        result = self.client.post(
            reverse("finding_create", args=[self.case.pk]),
            self.finding_payload(next="recommendation"),
        )
        finding = self.case.findings.get(number=2)
        self.assertRedirects(result, reverse("recommendation_create", args=[finding.pk]))

    def test_save_finding_only_returns_to_the_finding_in_the_builder(self):
        result = self.client.post(
            reverse("finding_create", args=[self.case.pk]),
            self.finding_payload(next=""),
        )
        finding = self.case.findings.get(number=2)
        self.assertRedirects(
            result, reverse("case_builder", args=[self.case.pk]) + f"#hallazgo-{finding.pk}"
        )

    def test_save_recommendation_and_add_another(self):
        result = self.client.post(
            reverse("recommendation_create", args=[self.finding.pk]),
            self.recommendation_payload(next="another"),
        )
        self.assertRedirects(result, reverse("recommendation_create", args=[self.finding.pk]))
        self.assertTrue(self.finding.recommendations.filter(number=2).exists())

    def test_recommendation_form_shows_finding_context_and_deadline_shortcuts(self):
        page = self.client.get(reverse("recommendation_create", args=[self.finding.pk]))
        self.assertContains(page, "Falta de conciliaciones")
        self.assertContains(page, "10 días hábiles")
        self.assertContains(page, 'data-value="2026-11-27"')
        self.assertContains(page, "Fecha general")
        self.assertContains(page, 'data-value="2026-12-18"')

    def test_deadline_shortcuts_skip_weekends_and_active_holidays(self):
        BusinessDayHoliday.objects.create(date=date(2026, 11, 16), name="Asueto de prueba")
        BusinessDayHoliday.objects.create(
            date=date(2026, 11, 17), name="Asueto inactivo", is_active=False
        )
        shortcuts = recommendation_deadline_shortcuts(self.case, (10, 30))
        self.assertEqual(shortcuts[0], {"label": "10 días hábiles", "value": date(2026, 11, 30)})
        self.assertEqual(shortcuts[1]["value"], add_business_days(date(2026, 11, 13), 30))
        self.assertEqual(shortcuts[-1], {"label": "Fecha general", "value": date(2026, 12, 18)})

    def test_deadline_shortcuts_count_from_today_without_report_date(self):
        self.case.report_date = None
        self.case.response_deadline = None
        shortcuts = recommendation_deadline_shortcuts(self.case, (10,), today=date(2026, 11, 18))
        self.assertEqual(shortcuts, [{"label": "10 días hábiles", "value": date(2026, 12, 2)}])

    def test_publication_requires_the_four_attributes_and_evidence(self):
        page = self.client.get(reverse("case_publish", args=[self.case.pk]))
        self.assertContains(page, "Complete el criterio, la causa y el efecto del hallazgo 1.")
        self.assertContains(page, "Complete las evidencias requeridas de la recomendación 1.1.")

        Finding.objects.filter(pk=self.finding.pk).update(
            criteria="Criterio.", cause="Causa.", effect="   "
        )
        page = self.client.get(reverse("case_publish", args=[self.case.pk]))
        self.assertContains(page, "Complete el efecto del hallazgo 1.")

    def test_builder_flags_incomplete_findings_and_recommendations(self):
        page = self.client.get(reverse("case_builder", args=[self.case.pk]))
        self.assertContains(page, "Falta redactar")
        self.assertContains(page, "Falta completar las evidencias requeridas")
        self.assertContains(page, f'id="hallazgo-{self.finding.pk}"')

    def test_duplicate_recommendation_creates_next_number_and_opens_it(self):
        self.recommendation.evidence_requirements = "Conciliaciones firmadas."
        self.recommendation.save()
        result = self.client.post(reverse("recommendation_duplicate", args=[self.recommendation.pk]))
        copy = self.finding.recommendations.get(number=2)
        self.assertRedirects(result, reverse("recommendation_edit", args=[copy.pk]))
        self.assertEqual(copy.text, self.recommendation.text)
        self.assertEqual(copy.responsible_organization, self.center)
        self.assertEqual(copy.deadline, self.recommendation.deadline)
        self.assertEqual(copy.evidence_requirements, "Conciliaciones firmadas.")
        self.assertIsNone(copy.source_recommendation)
        self.assertTrue(
            ActivityLog.objects.filter(
                case=self.case, action="recommendation_duplicated"
            ).exists()
        )

    def test_duplicate_requires_post_and_edit_permission(self):
        url = reverse("recommendation_duplicate", args=[self.recommendation.pk])
        self.assertEqual(self.client.get(url).status_code, 405)

        self.client.force_login(self.other_auditor)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertEqual(self.finding.recommendations.count(), 1)

    def test_published_case_cannot_be_duplicated_into(self):
        self.case.status = AuditCase.Status.PUBLISHED
        self.case.save(update_fields=["status"])
        result = self.client.post(
            reverse("recommendation_duplicate", args=[self.recommendation.pk])
        )
        self.assertEqual(result.status_code, 403)
        self.assertEqual(self.finding.recommendations.count(), 1)

    def test_edit_form_keeps_existing_dates_in_native_date_inputs(self):
        # <input type="date"> solo acepta AAAA-MM-DD; con el formato regional el campo
        # se mostraba vacío y la fecha se perdía al guardar.
        page = self.client.get(reverse("recommendation_edit", args=[self.recommendation.pk]))
        self.assertContains(page, 'type="date" name="deadline" value="2026-12-18"', html=False)
        page = self.client.get(reverse("case_edit", args=[self.case.pk]))
        self.assertContains(page, 'name="report_date" value="2026-11-13"', html=False)

    def test_finding_form_offers_frequent_phrases(self):
        page = self.client.get(reverse("finding_create", args=[self.case.pk]))
        self.assertContains(page, 'data-insert-into="id_criteria"')
        self.assertContains(page, 'data-text="la Ley General de Educación"')
        self.assertContains(page, 'data-insert-into="id_cause"')
        self.assertContains(page, 'data-insert-into="id_effect"')
        self.assertNotContains(page, 'data-insert-into="id_condition"')

    def test_recommendation_form_offers_evidence_lines_and_the_auditors_own(self):
        own_case = AuditCase.objects.create(
            reference="IA-BUILDER-PREVIO",
            title="Expediente anterior",
            audited_organization=self.center,
            status=AuditCase.Status.CLOSED,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        foreign_case = AuditCase.objects.create(
            reference="IA-BUILDER-AJENO",
            title="Expediente de otro auditor",
            audited_organization=self.center,
            status=AuditCase.Status.CLOSED,
            assigned_auditor=self.other_auditor,
            created_by=self.other_auditor,
        )
        own_finding = Finding.objects.create(
            case=own_case, number=1, title="Previo", risk_level=Finding.RiskLevel.LOW
        )
        foreign_finding = Finding.objects.create(
            case=foreign_case, number=1, title="Ajeno", risk_level=Finding.RiskLevel.LOW
        )
        for number, evidence in enumerate(
            [
                "Planilla de asistencia firmada.\nConciliaciones bancarias firmadas.",
                "- Planilla de asistencia firmada.\nLínea usada una sola vez.",
            ],
            start=1,
        ):
            Recommendation.objects.create(
                finding=own_finding,
                number=number,
                text="Previa",
                responsible_organization=self.center,
                evidence_requirements=evidence,
            )
        for number in (1, 2):
            Recommendation.objects.create(
                finding=foreign_finding,
                number=number,
                text="Ajena",
                responsible_organization=self.center,
                evidence_requirements="Bitácora reservada de otro auditor.",
            )

        page = self.client.get(reverse("recommendation_create", args=[self.finding.pk]))
        self.assertContains(page, 'data-text="Conciliaciones bancarias firmadas."', count=1)
        self.assertContains(page, "Usadas por usted")
        self.assertContains(page, 'data-text="Planilla de asistencia firmada."')
        self.assertNotContains(page, "Línea usada una sola vez.")
        self.assertNotContains(page, "Bitácora reservada de otro auditor.")
        self.assertContains(page, 'data-insert-into="id_text"')

    def test_learned_evidence_labels_are_shortened(self):
        long_line = "Certificación del contador sobre los saldos conciliados al cierre."
        own_finding = self.finding
        for number in (2, 3):
            Recommendation.objects.create(
                finding=own_finding,
                number=number,
                text="Previa",
                responsible_organization=self.center,
                evidence_requirements=long_line,
            )
        learned = learned_evidence_snippets(Recommendation.objects.all())
        self.assertEqual(learned[0]["text"], long_line)
        self.assertTrue(learned[0]["label"].endswith("…"))
        self.assertLessEqual(len(learned[0]["label"]), 32)


class NumberedCaseSetup:
    """Expediente en borrador con tres hallazgos; el primero tiene tres recomendaciones."""

    def setUp(self):
        self.center = Organization.objects.create(
            code="10755", name="Centro Dos", kind=Organization.Kind.EDUCATIONAL_CENTER
        )
        self.auditor = User.objects.create_user(
            username="auditor-numeracion", role=User.Role.AUDITOR, must_change_password=False
        )
        self.auditor.assigned_organizations.add(self.center)
        self.case = AuditCase.objects.create(
            reference="IA-NUM-001",
            title="Numeración",
            audited_organization=self.center,
            status=AuditCase.Status.DRAFT,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
            response_deadline=date(2026, 12, 18),
        )
        self.findings = [
            Finding.objects.create(
                case=self.case, number=number, title=f"Hallazgo {number}", risk_level=Finding.RiskLevel.LOW
            )
            for number in (1, 2, 3)
        ]
        self.recommendations = [
            Recommendation.objects.create(
                finding=self.findings[0],
                number=number,
                text=f"Recomendación {number}",
                responsible_organization=self.center,
            )
            for number in (1, 2, 3)
        ]
        self.client.force_login(self.auditor)


class AutomaticNumberingTests(NumberedCaseSetup, TestCase):
    """El sistema numera hallazgos y recomendaciones sin huecos y permite reordenarlos en borrador."""

    def finding_numbers(self):
        return list(self.case.findings.order_by("number").values_list("title", "number"))

    def recommendation_numbers(self):
        return list(
            self.findings[0].recommendations.order_by("number").values_list("text", "number")
        )

    def test_forms_do_not_ask_for_the_number(self):
        finding_page = self.client.get(reverse("finding_create", args=[self.case.pk]))
        self.assertNotContains(finding_page, 'name="number"')
        self.assertContains(finding_page, "Agregar hallazgo 4")
        recommendation_page = self.client.get(
            reverse("recommendation_create", args=[self.findings[0].pk])
        )
        self.assertNotContains(recommendation_page, 'name="number"')
        self.assertContains(recommendation_page, "Agregar recomendación 1.4")

    def test_a_posted_number_is_ignored_and_the_next_one_is_assigned(self):
        response = self.client.post(
            reverse("finding_create", args=[self.case.pk]),
            {"number": 1, "title": "Nuevo", "risk_level": Finding.RiskLevel.LOW},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.case.findings.get(title="Nuevo").number, 4)

        response = self.client.post(
            reverse("recommendation_create", args=[self.findings[0].pk]),
            {"number": 1, "text": "Nueva", "responsible_organization": self.center.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.findings[0].recommendations.get(text="Nueva").number, 4)

    def test_editing_keeps_the_number(self):
        finding = self.findings[1]
        self.client.post(
            reverse("finding_edit", args=[finding.pk]),
            {"number": 1, "title": "Editado", "risk_level": Finding.RiskLevel.LOW},
        )
        finding.refresh_from_db()
        self.assertEqual((finding.title, finding.number), ("Editado", 2))

    def test_deleting_a_finding_renumbers_the_following_ones(self):
        self.client.post(reverse("finding_delete", args=[self.findings[0].pk]))
        self.assertEqual(self.finding_numbers(), [("Hallazgo 2", 1), ("Hallazgo 3", 2)])

    def test_deleting_a_recommendation_renumbers_the_following_ones(self):
        response = self.client.post(reverse("recommendation_delete", args=[self.recommendations[0].pk]))
        self.assertRedirects(
            response,
            reverse("case_builder", args=[self.case.pk]) + f"#hallazgo-{self.findings[0].pk}",
        )
        self.assertEqual(
            self.recommendation_numbers(), [("Recomendación 2", 1), ("Recomendación 3", 2)]
        )

    def test_move_a_finding_down_and_up(self):
        url = reverse("finding_move", args=[self.findings[0].pk])
        self.client.post(url, {"direction": "down"})
        self.assertEqual(
            self.finding_numbers(), [("Hallazgo 2", 1), ("Hallazgo 1", 2), ("Hallazgo 3", 3)]
        )
        self.client.post(url, {"direction": "up"})
        self.assertEqual(
            self.finding_numbers(), [("Hallazgo 1", 1), ("Hallazgo 2", 2), ("Hallazgo 3", 3)]
        )
        log = ActivityLog.objects.filter(action="finding_moved").first()
        self.assertEqual(log.details, {"from": 2, "to": 1})

    def test_moving_past_the_ends_changes_nothing(self):
        self.client.post(reverse("finding_move", args=[self.findings[0].pk]), {"direction": "up"})
        self.client.post(reverse("finding_move", args=[self.findings[2].pk]), {"direction": "down"})
        self.assertEqual(
            self.finding_numbers(), [("Hallazgo 1", 1), ("Hallazgo 2", 2), ("Hallazgo 3", 3)]
        )
        self.assertFalse(ActivityLog.objects.filter(action="finding_moved").exists())

    def test_move_a_recommendation_up(self):
        self.client.post(
            reverse("recommendation_move", args=[self.recommendations[2].pk]), {"direction": "up"}
        )
        self.assertEqual(
            self.recommendation_numbers(),
            [("Recomendación 1", 1), ("Recomendación 3", 2), ("Recomendación 2", 3)],
        )

    def test_invalid_direction_is_rejected(self):
        response = self.client.post(
            reverse("finding_move", args=[self.findings[0].pk]), {"direction": "sideways"}
        )
        self.assertEqual(response.status_code, 404)

    def test_builder_shows_move_buttons_only_where_they_apply(self):
        page = self.client.get(reverse("case_builder", args=[self.case.pk]))
        self.assertNotContains(page, 'aria-label="Subir el hallazgo 1"')
        self.assertContains(page, 'aria-label="Bajar el hallazgo 1"')
        self.assertContains(page, 'aria-label="Subir el hallazgo 3"')
        self.assertNotContains(page, 'aria-label="Bajar el hallazgo 3"')
        self.assertContains(page, 'aria-label="Subir la recomendación 1.2"')
        self.assertNotContains(page, 'aria-label="Bajar la recomendación 1.3"')

    def test_only_draft_cases_can_be_reordered(self):
        AuditCase.objects.filter(pk=self.case.pk).update(status=AuditCase.Status.PUBLISHED)
        response = self.client.post(
            reverse("finding_move", args=[self.findings[0].pk]), {"direction": "down"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.findings[0].__class__.objects.get(pk=self.findings[0].pk).number, 1)


class FormAsideTests(NumberedCaseSetup, TestCase):
    """Columna lateral del editor: lista de avance del formulario y mapa del expediente."""

    def test_new_finding_lists_its_fields_with_their_requirement(self):
        page = self.client.get(reverse("finding_create", args=[self.case.pk]))
        self.assertContains(page, "En este formulario")
        self.assertContains(page, '<span data-checklist-done>0</span> de 6 listos', html=False)
        self.assertContains(page, 'data-checklist-item="id_title" data-kind="required"')
        self.assertContains(page, 'data-checklist-item="id_condition" data-kind="publish" data-placeholders')
        self.assertContains(page, "Antes de enviar", count=4)
        self.assertContains(page, 'href="#id_effect"')

    def test_existing_values_count_as_done_and_placeholders_are_flagged(self):
        finding = self.findings[1]
        finding.condition = "Durante [período revisado] no se concilió."
        finding.criteria = "Instructivo de fondos."
        finding.save()
        page = self.client.get(reverse("finding_edit", args=[finding.pk]))
        # Título, riesgo y criterio listos; la condición tiene datos por completar.
        self.assertContains(page, '<span data-checklist-done>3</span> de 6 listos', html=False)
        self.assertContains(page, 'ui-fieldlist-item is-placeholder" data-checklist-item="id_condition"')
        self.assertContains(page, "Completar [corchetes]")

    def test_fields_with_errors_are_marked_for_review(self):
        page = self.client.post(
            reverse("finding_create", args=[self.case.pk]),
            {"title": "", "risk_level": Finding.RiskLevel.LOW},
        )
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'ui-fieldlist-item is-error" data-checklist-item="id_title"')
        self.assertContains(page, "Revisar")

    def test_recommendation_checklist_marks_deadline_and_evidence_before_sending(self):
        page = self.client.get(reverse("recommendation_create", args=[self.findings[0].pk]))
        self.assertContains(page, 'data-checklist-item="id_deadline" data-kind="publish"')
        self.assertContains(page, 'data-checklist-item="id_evidence_requirements" data-kind="publish"')
        # El responsable y la fecha general vienen precargados del expediente.
        self.assertContains(page, '<span data-checklist-done>2</span> de 4 listos', html=False)

    def test_short_forms_do_not_show_the_checklist(self):
        page = self.client.get(reverse("password_change"))
        self.assertNotContains(page, "data-form-checklist")

    def test_outline_places_the_new_finding_at_the_end(self):
        page = self.client.get(reverse("finding_create", args=[self.case.pk]))
        self.assertContains(page, "Hallazgos del expediente")
        for finding in self.findings:
            self.assertContains(page, reverse("finding_edit", args=[finding.pk]))
        self.assertContains(page, '<span class="ui-outline-number">4</span><span class="ui-outline-text">Nuevo hallazgo</span>')
        self.assertContains(page, "3 recomendaciones")
        # Los hallazgos 2 y 3 no tienen recomendaciones ni condición: aparecen incompletos.
        self.assertContains(page, "ui-outline-flag", count=3)

    def test_outline_opens_the_current_finding_and_shows_the_new_recommendation(self):
        page = self.client.get(reverse("recommendation_create", args=[self.findings[0].pk]))
        for recommendation in self.recommendations:
            self.assertContains(page, reverse("recommendation_edit", args=[recommendation.pk]))
        self.assertContains(page, '<span class="ui-outline-number">1.4</span><span class="ui-outline-text">Nueva recomendación</span>')
        self.assertNotContains(page, "3 recomendaciones")

    def test_outline_marks_the_item_being_edited(self):
        page = self.client.get(reverse("recommendation_edit", args=[self.recommendations[1].pk]))
        url = reverse("recommendation_edit", args=[self.recommendations[1].pk])
        self.assertContains(page, f'class="ui-outline-link is-current" href="{url}" aria-current="page"')
        page = self.client.get(reverse("finding_edit", args=[self.findings[2].pk]))
        url = reverse("finding_edit", args=[self.findings[2].pk])
        self.assertContains(page, f'class="ui-outline-link is-current" href="{url}" aria-current="page"')
