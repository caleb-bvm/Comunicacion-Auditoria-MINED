import hashlib
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Exists, Max, OuterRef, Prefetch, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from django.views.generic import ListView, TemplateView

from apps.accounts.models import User
from apps.institutions.models import Organization, SchoolBoardPeriod

from .forms import (
    AuditCaseForm,
    AuditorReassignmentForm,
    CaseReportDocumentForm,
    ClosureRequestForm,
    DeadlineExtensionForm,
    DecisionResolutionForm,
    FindingForm,
    HistoricalDocumentForm,
    HistoricalRecommendationForm,
    HistoricalRecommendationImportForm,
    RecommendationForm,
    ResponseForm,
    ReviewForm,
)
from .models import (
    ActivityLog,
    AuditCase,
    AuditDocument,
    CaseDecision,
    DeadlineExtension,
    Evidence,
    Finding,
    HistoricalRecommendation,
    Recommendation,
    Response,
    Review,
)
from .pdf import build_response_receipt
from .services import (
    add_business_days,
    copy_historical_recommendations,
    create_audit_document,
    next_document_version,
    with_effective_deadline,
)
from .statistics import (
    RESPONSE_DUE_STATUSES,
    TERMINAL_RECOMMENDATION_STATUSES,
    build_case_statistics,
    percentage,
)


def get_client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")


def log_activity(request, action, case=None, target=None, details=None):
    ActivityLog.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        case=case,
        action=action,
        target_type=target.__class__.__name__ if target else "",
        target_id=str(target.pk) if target else "",
        details=details or {},
        ip_address=get_client_ip(request),
    )


def user_can_create_cases(user):
    return user.is_authenticated and user.role == User.Role.AUDITOR


def user_is_director(user):
    return user.is_authenticated and user.role == User.Role.AUDIT_MANAGER


def institutional_username(organization):
    """Build a stable, unique username from the official center code."""
    identifier = slugify(organization.code) or str(organization.pk)
    base_username = f"centro.{identifier}"[:150]
    username = base_username
    suffix = 2
    while User.objects.filter(username=username).exists():
        suffix_text = f".{suffix}"
        username = f"{base_username[:150 - len(suffix_text)]}{suffix_text}"
        suffix += 1
    return username


def user_can_edit_case(user, case):
    if not user.is_authenticated or case.status != AuditCase.Status.DRAFT:
        return False
    return user.role == User.Role.AUDITOR and case.assigned_auditor_id == user.pk


def user_can_access_response(user, response):
    case = response.recommendation.finding.case
    if user.is_superuser or user.role in {
        User.Role.TECHNICAL_ADMIN,
        User.Role.AUDIT_MANAGER,
    }:
        return True
    if user.role == User.Role.AUDITOR:
        return case.assigned_auditor_id == user.pk
    return bool(
        user.role == User.Role.INSTITUTION
        and user.organization_id
        and response.recommendation.responsible_organization_id == user.organization_id
    )


def user_can_access_document(user, document):
    if user.is_superuser or user.role in {
        User.Role.TECHNICAL_ADMIN,
        User.Role.AUDIT_MANAGER,
    }:
        return True
    if user.role == User.Role.AUDITOR:
        return bool(
            document.document_type == AuditDocument.DocumentType.HISTORICAL_REPORT
            or (document.case and document.case.assigned_auditor_id == user.pk)
        )
    return bool(
        user.role == User.Role.INSTITUTION
        and user.organization_id == document.organization_id
        and document.visibility == AuditDocument.Visibility.INSTITUTION
        and document.status in {
            AuditDocument.Status.HISTORICAL,
            AuditDocument.Status.APPROVED,
        }
    )


def get_editable_case(user, pk):
    case = get_object_or_404(
        AuditCase.objects.select_related("audited_organization", "assigned_auditor"),
        pk=pk,
    )
    if not user_can_edit_case(user, case):
        raise PermissionDenied("No tiene autorización para modificar este expediente.")
    return case


def publication_issues(case):
    findings = list(case.findings.prefetch_related("recommendations"))
    issues = []
    report_document = case.documents.filter(
        document_type=AuditDocument.DocumentType.REPORT,
        status__in=[
            AuditDocument.Status.DRAFT,
            AuditDocument.Status.PENDING_APPROVAL,
        ],
    ).order_by("-version").first()
    if not report_document:
        issues.append("Cargue el informe elaborado en Word antes de solicitar su aprobación.")
    elif Path(report_document.original_filename or report_document.file.name).suffix.lower() != ".docx":
        issues.append("La versión que se someterá a aprobación debe estar en formato Word (.docx).")
    if not case.report_date:
        issues.append("Indique la fecha oficial del informe.")
    if not case.response_deadline:
        issues.append("Indique la fecha límite general de respuesta.")
    if not findings:
        issues.append("Registre al menos un hallazgo.")
    for finding in findings:
        recommendations = list(finding.recommendations.all())
        if not recommendations:
            issues.append(f"El hallazgo {finding.number} necesita al menos una recomendación.")
        for recommendation in recommendations:
            if not recommendation.deadline:
                issues.append(
                    f"La recomendación {finding.number}.{recommendation.number} necesita fecha límite."
                )
    return issues


def closure_issues(case):
    recommendations = Recommendation.objects.filter(finding__case=case)
    issues = []
    if not recommendations.exists():
        issues.append("El expediente no contiene recomendaciones.")
        return issues
    open_recommendations = recommendations.exclude(
        status__in=[
            Recommendation.Status.COMPLIED,
            Recommendation.Status.PARTIAL,
            Recommendation.Status.NOT_COMPLIED,
        ]
    ).count()
    if open_recommendations:
        issues.append(
            f"Aún hay {open_recommendations} recomendación"
            f"{'es' if open_recommendations != 1 else ''} sin resultado definitivo."
        )
    return issues


def accessible_cases(user):
    queryset = AuditCase.objects.select_related("audited_organization", "assigned_auditor")
    if user.is_superuser or user.role in {User.Role.TECHNICAL_ADMIN, User.Role.AUDIT_MANAGER}:
        return queryset
    if user.role == User.Role.AUDITOR:
        return queryset.filter(assigned_auditor=user)
    if not user.organization_id:
        return queryset.none()
    return queryset.exclude(
        status__in=[AuditCase.Status.DRAFT, AuditCase.Status.PENDING_PUBLICATION]
    ).filter(
        Q(audited_organization_id=user.organization_id)
        | Q(findings__recommendations__responsible_organization_id=user.organization_id)
    ).distinct()


def get_accessible_case(user, pk):
    return get_object_or_404(accessible_cases(user), pk=pk)


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "audits/dashboard.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role == User.Role.AUDIT_MANAGER:
            return redirect("director_dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cases = accessible_cases(self.request.user)
        context["recent_cases"] = cases[:6]
        statistics = build_case_statistics(cases)
        context.update(statistics)
        if self.request.user.is_audit_staff:
            context["pending_recommendations"] = Recommendation.objects.filter(
                finding__case__in=cases,
                status__in=[
                    Recommendation.Status.SUBMITTED,
                    Recommendation.Status.UNDER_REVIEW,
                ]
            ).count()
        elif self.request.user.organization_id:
            context["pending_recommendations"] = Recommendation.objects.filter(
                responsible_organization_id=self.request.user.organization_id,
                status__in=[Recommendation.Status.PENDING, Recommendation.Status.CORRECTION_REQUIRED],
            ).count()
        else:
            context["pending_recommendations"] = 0

        if self.request.user.role == User.Role.AUDITOR:
            today = timezone.localdate()
            pending_responses = (
                Response.objects.filter(
                    recommendation__finding__case__in=cases,
                    review__isnull=True,
                )
                .select_related(
                    "recommendation__finding__case__audited_organization"
                )
                .order_by("submitted_at")[:6]
            )
            urgent_recommendations = list(
                with_effective_deadline(
                    Recommendation.objects.filter(
                        finding__case__in=cases,
                        status__in=RESPONSE_DUE_STATUSES,
                    ).select_related("finding__case__audited_organization")
                )
                .filter(current_deadline__lte=today + timedelta(days=7))
                .order_by("current_deadline")[:6]
            )
            attention_items = [
                {
                    "kind": "review",
                    "label": "Respuesta por revisar",
                    "case": response.recommendation.finding.case,
                    "organization": response.recommendation.finding.case.audited_organization,
                    "date": response.submitted_at,
                    "response": response,
                    "sort_key": (1, response.submitted_at),
                }
                for response in pending_responses
            ]
            attention_items.extend(
                {
                    "kind": (
                        "overdue" if recommendation.current_deadline < today else "due_soon"
                    ),
                    "label": (
                        "Plazo vencido"
                        if recommendation.current_deadline < today
                        else "Plazo próximo"
                    ),
                    "case": recommendation.finding.case,
                    "organization": recommendation.finding.case.audited_organization,
                    "date": recommendation.current_deadline,
                    "recommendation": recommendation,
                    "sort_key": (
                        0 if recommendation.current_deadline < today else 2,
                        recommendation.current_deadline,
                    ),
                }
                for recommendation in urgent_recommendations
            )
            context["attention_items"] = sorted(
                attention_items, key=lambda item: item["sort_key"]
            )[:6]
        return context


def institution_history(request):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    if request.user.role != User.Role.INSTITUTION or not request.user.organization_id:
        raise PermissionDenied("Esta sección corresponde a las instituciones responsables.")
    organization = request.user.organization
    cases = accessible_cases(request.user).exclude(
        status__in=[AuditCase.Status.DRAFT, AuditCase.Status.PENDING_PUBLICATION]
    )
    documents = AuditDocument.objects.filter(
        organization=organization,
        visibility=AuditDocument.Visibility.INSTITUTION,
        status__in=[AuditDocument.Status.HISTORICAL, AuditDocument.Status.APPROVED],
    ).select_related("case")
    recommendations = Recommendation.objects.filter(
        Q(finding__case__audited_organization=organization)
        | Q(responsible_organization=organization),
        finding__case__in=cases,
    ).select_related("finding__case", "responsible_organization").distinct()
    responses = Response.objects.filter(
        recommendation__responsible_organization=organization,
        recommendation__finding__case__in=cases,
    ).select_related("recommendation__finding__case").prefetch_related("evidence")
    historical_recommendations = HistoricalRecommendation.objects.filter(
        source_document__organization=organization,
        source_document__visibility=AuditDocument.Visibility.INSTITUTION,
        source_document__status=AuditDocument.Status.HISTORICAL,
    ).select_related("source_document", "responsible_organization")
    return render(
        request,
        "audits/institution_history.html",
        {
            "organization": organization,
            "cases": cases,
            "documents": documents,
            "recommendations": recommendations,
            "historical_recommendations": historical_recommendations,
            "recommendation_count": (
                recommendations.count() + historical_recommendations.count()
            ),
            "responses": responses,
        },
    )


class DirectorDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "audits/director_dashboard.html"

    def dispatch(self, request, *args, **kwargs):
        if not user_is_director(request.user):
            raise PermissionDenied("Esta sección es exclusiva de la Dirección de Auditoría.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        cases = AuditCase.objects.all()
        pending_decisions = CaseDecision.objects.filter(status=CaseDecision.Status.PENDING)
        terminal_recommendations = Recommendation.objects.filter(
            status__in=[
                Recommendation.Status.COMPLIED,
                Recommendation.Status.PARTIAL,
                Recommendation.Status.NOT_COMPLIED,
            ]
        )
        complied = terminal_recommendations.filter(status=Recommendation.Status.COMPLIED).count()
        terminal_count = terminal_recommendations.count()

        active_institutional_user = User.objects.filter(
            organization_id=OuterRef("pk"),
            role=User.Role.INSTITUTION,
            is_active=True,
        )
        centers_without_users = (
            Organization.objects.filter(
                recommendations__finding__case__status__in=[
                    AuditCase.Status.PUBLISHED,
                    AuditCase.Status.IN_RESPONSE,
                    AuditCase.Status.UNDER_REVIEW,
                    AuditCase.Status.CORRECTION_REQUIRED,
                    AuditCase.Status.PENDING_CLOSURE,
                ]
            )
            .annotate(has_active_user=Exists(active_institutional_user))
            .filter(has_active_user=False)
            .distinct()
        )
        auditor_workload = (
            User.objects.filter(role=User.Role.AUDITOR, is_active=True)
            .annotate(
                open_cases_count=Count(
                    "assigned_cases",
                    filter=~Q(assigned_cases__status=AuditCase.Status.CLOSED),
                    distinct=True,
                ),
                pending_reviews_count=Count(
                    "assigned_cases__findings__recommendations__responses",
                    filter=Q(
                        assigned_cases__findings__recommendations__responses__review__isnull=True
                    ),
                    distinct=True,
                ),
            )
            .order_by("-open_cases_count", "first_name", "last_name", "username")
        )

        context.update(
            {
                "total_cases": cases.count(),
                "open_cases": cases.exclude(
                    status__in=[AuditCase.Status.DRAFT, AuditCase.Status.CLOSED]
                ).count(),
                "pending_decisions_count": pending_decisions.count(),
                "pending_decisions": pending_decisions.select_related(
                    "case__audited_organization", "case__assigned_auditor", "requested_by"
                )[:6],
                "overdue_recommendations": with_effective_deadline().filter(
                    current_deadline__lt=today,
                    status__in=RESPONSE_DUE_STATUSES,
                ).count(),
                "critical_findings": Finding.objects.filter(
                    risk_level=Finding.RiskLevel.CRITICAL
                )
                .exclude(case__status=AuditCase.Status.CLOSED)
                .count(),
                "pending_reviews": Response.objects.filter(review__isnull=True).count(),
                "compliance_rate": round((complied / terminal_count) * 100) if terminal_count else 0,
                "centers_without_users_count": centers_without_users.count(),
                "centers_without_users": centers_without_users.order_by("name")[:6],
                "auditor_workload": auditor_workload,
                "recent_decisions": CaseDecision.objects.exclude(
                    status=CaseDecision.Status.PENDING
                ).select_related("case", "decided_by")[:5],
            }
        )
        return context


class DirectorStatisticsView(LoginRequiredMixin, TemplateView):
    template_name = "audits/director_statistics.html"

    PERIOD_CHOICES = (
        ("year", "Año actual"),
        ("30", "Últimos 30 días"),
        ("90", "Últimos 90 días"),
        ("previous_year", "Año anterior"),
        ("all", "Todo el historial"),
        ("custom", "Rango personalizado"),
    )

    def dispatch(self, request, *args, **kwargs):
        if not user_is_director(request.user):
            raise PermissionDenied("Esta sección es exclusiva de la Dirección de Auditoría.")
        return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def _date_value(raw_value):
        try:
            return date.fromisoformat(raw_value) if raw_value else None
        except ValueError:
            return None

    def _filtered_cases(self):
        today = timezone.localdate()
        period = self.request.GET.get("period", "year")
        valid_periods = {value for value, _label in self.PERIOD_CHOICES}
        errors = []
        if period not in valid_periods:
            period = "year"

        start_date = end_date = None
        if period == "year":
            start_date = date(today.year, 1, 1)
            end_date = today
        elif period == "30":
            start_date = today - timedelta(days=29)
            end_date = today
        elif period == "90":
            start_date = today - timedelta(days=89)
            end_date = today
        elif period == "previous_year":
            start_date = date(today.year - 1, 1, 1)
            end_date = date(today.year - 1, 12, 31)
        elif period == "custom":
            start_date = self._date_value(self.request.GET.get("start"))
            end_date = self._date_value(self.request.GET.get("end"))
            if not start_date or not end_date:
                errors.append("Indique una fecha inicial y una fecha final válidas.")
            elif start_date > end_date:
                errors.append("La fecha inicial no puede ser posterior a la fecha final.")

        cases = AuditCase.objects.select_related(
            "audited_organization", "assigned_auditor"
        )
        if errors:
            cases = cases.none()
        if start_date and end_date and start_date <= end_date:
            cases = cases.filter(created_at__date__range=(start_date, end_date))

        selected_auditor = None
        auditor_id = self.request.GET.get("auditor", "")
        if auditor_id:
            selected_auditor = (
                User.objects.filter(pk=int(auditor_id), role=User.Role.AUDITOR).first()
                if auditor_id.isdigit()
                else None
            )
            if selected_auditor:
                cases = cases.filter(assigned_auditor=selected_auditor)
            else:
                errors.append("El auditor seleccionado no es válido.")
                cases = cases.none()

        selected_organization = None
        organization_id = self.request.GET.get("organization", "")
        if organization_id:
            selected_organization = (
                Organization.objects.filter(pk=int(organization_id)).first()
                if organization_id.isdigit()
                else None
            )
            if selected_organization:
                cases = cases.filter(audited_organization=selected_organization)
            else:
                errors.append("La institución seleccionada no es válida.")
                cases = cases.none()

        selected_status = self.request.GET.get("status", "")
        valid_statuses = {value for value, _label in AuditCase.Status.choices}
        if selected_status in valid_statuses:
            cases = cases.filter(status=selected_status)
        else:
            if selected_status:
                errors.append("El estado seleccionado no es válido.")
                cases = cases.none()
            selected_status = ""

        return cases, {
            "selected_period": period,
            "start_date": start_date,
            "end_date": end_date,
            "selected_auditor": selected_auditor,
            "selected_organization": selected_organization,
            "selected_status": selected_status,
            "filter_errors": errors,
        }

    @staticmethod
    def _auditor_rows(cases, selected_auditor=None):
        recommendations = Recommendation.objects.filter(finding__case__in=cases)
        responses = Response.objects.filter(recommendation__in=recommendations)
        overdue = with_effective_deadline(recommendations).filter(
            current_deadline__lt=timezone.localdate(),
            status__in=RESPONSE_DUE_STATUSES,
        )
        case_counts = {
            row["assigned_auditor_id"]: row
            for row in cases.values("assigned_auditor_id").annotate(
                cases_count=Count("pk"),
                open_cases_count=Count(
                    "pk", filter=~Q(status=AuditCase.Status.CLOSED)
                ),
            )
        }
        recommendation_counts = {
            row["finding__case__assigned_auditor_id"]: row
            for row in recommendations.values(
                "finding__case__assigned_auditor_id"
            ).annotate(
                recommendation_count=Count("pk"),
                terminal_count=Count(
                    "pk", filter=Q(status__in=TERMINAL_RECOMMENDATION_STATUSES)
                ),
                complied_count=Count(
                    "pk", filter=Q(status=Recommendation.Status.COMPLIED)
                ),
            )
        }
        pending_review_counts = dict(
            responses.filter(review__isnull=True)
            .values("recommendation__finding__case__assigned_auditor_id")
            .annotate(total=Count("pk"))
            .values_list(
                "recommendation__finding__case__assigned_auditor_id", "total"
            )
        )
        overdue_counts = dict(
            overdue.values("finding__case__assigned_auditor_id")
            .annotate(total=Count("pk"))
            .values_list("finding__case__assigned_auditor_id", "total")
        )
        auditor_ids = set(case_counts)
        if selected_auditor:
            auditors = User.objects.filter(pk=selected_auditor.pk)
        else:
            auditors = User.objects.filter(
                Q(role=User.Role.AUDITOR, is_active=True) | Q(pk__in=auditor_ids)
            ).distinct()
        rows = []
        for auditor in auditors:
            case_row = case_counts.get(auditor.pk, {})
            recommendation_row = recommendation_counts.get(auditor.pk, {})
            rows.append(
                {
                    "auditor": auditor,
                    "cases_count": case_row.get("cases_count", 0),
                    "open_cases_count": case_row.get("open_cases_count", 0),
                    "recommendation_count": recommendation_row.get(
                        "recommendation_count", 0
                    ),
                    "pending_reviews_count": pending_review_counts.get(auditor.pk, 0),
                    "overdue_count": overdue_counts.get(auditor.pk, 0),
                    "compliance_rate": percentage(
                        recommendation_row.get("complied_count", 0),
                        recommendation_row.get("terminal_count", 0),
                    ),
                }
            )
        return sorted(
            rows,
            key=lambda row: (
                -row["overdue_count"],
                -row["pending_reviews_count"],
                -row["open_cases_count"],
                row["auditor"].get_full_name() or row["auditor"].username,
            ),
        )

    @staticmethod
    def _organization_rows(cases):
        recommendations = Recommendation.objects.filter(finding__case__in=cases)
        findings = Finding.objects.filter(case__in=cases)
        overdue = with_effective_deadline(recommendations).filter(
            current_deadline__lt=timezone.localdate(),
            status__in=RESPONSE_DUE_STATUSES,
        )
        case_rows = list(
            cases.values(
                "audited_organization_id",
                "audited_organization__code",
                "audited_organization__name",
            ).annotate(
                cases_count=Count("pk"),
                open_cases_count=Count(
                    "pk", filter=~Q(status=AuditCase.Status.CLOSED)
                ),
            )
        )
        recommendation_counts = {
            row["finding__case__audited_organization_id"]: row
            for row in recommendations.values(
                "finding__case__audited_organization_id"
            ).annotate(
                recommendation_count=Count("pk"),
                terminal_count=Count(
                    "pk", filter=Q(status__in=TERMINAL_RECOMMENDATION_STATUSES)
                ),
                complied_count=Count(
                    "pk", filter=Q(status=Recommendation.Status.COMPLIED)
                ),
            )
        }
        overdue_counts = dict(
            overdue.values("finding__case__audited_organization_id")
            .annotate(total=Count("pk"))
            .values_list("finding__case__audited_organization_id", "total")
        )
        critical_counts = dict(
            findings.filter(risk_level=Finding.RiskLevel.CRITICAL)
            .values("case__audited_organization_id")
            .annotate(total=Count("pk"))
            .values_list("case__audited_organization_id", "total")
        )
        rows = []
        for case_row in case_rows:
            organization_id = case_row["audited_organization_id"]
            recommendation_row = recommendation_counts.get(organization_id, {})
            rows.append(
                {
                    "organization_id": organization_id,
                    "code": case_row["audited_organization__code"],
                    "name": case_row["audited_organization__name"],
                    "cases_count": case_row["cases_count"],
                    "open_cases_count": case_row["open_cases_count"],
                    "recommendation_count": recommendation_row.get(
                        "recommendation_count", 0
                    ),
                    "overdue_count": overdue_counts.get(organization_id, 0),
                    "critical_count": critical_counts.get(organization_id, 0),
                    "compliance_rate": percentage(
                        recommendation_row.get("complied_count", 0),
                        recommendation_row.get("terminal_count", 0),
                    ),
                }
            )
        return sorted(
            rows,
            key=lambda row: (
                -row["overdue_count"],
                -row["critical_count"],
                -row["open_cases_count"],
                row["name"],
            ),
        )[:10]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cases, filters = self._filtered_cases()
        statistics = build_case_statistics(cases)
        context.update(statistics)
        context.update(filters)
        context.update(
            {
                "period_choices": self.PERIOD_CHOICES,
                "auditor_options": User.objects.filter(
                    role=User.Role.AUDITOR
                ).order_by("first_name", "last_name", "username"),
                "organization_options": Organization.objects.filter(
                    audit_cases__isnull=False
                ).distinct().order_by("name"),
                "status_choices": AuditCase.Status.choices,
                "auditor_statistics": self._auditor_rows(
                    cases, filters["selected_auditor"]
                ),
                "organization_statistics": self._organization_rows(cases),
            }
        )
        return context


class DirectorEducationalCenterListView(LoginRequiredMixin, ListView):
    template_name = "audits/director_educational_center_list.html"
    context_object_name = "centers"
    paginate_by = 25

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not user_is_director(request.user):
            raise PermissionDenied("Esta sección es exclusiva de la Dirección de Auditoría.")
        return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def center_queryset():
        institutional_accounts = User.objects.filter(
            role=User.Role.INSTITUTION
        ).order_by("-is_active", "username")
        return (
            Organization.objects.filter(kind=Organization.Kind.EDUCATIONAL_CENTER)
            .annotate(
                active_user_count=Count(
                    "users",
                    filter=Q(users__role=User.Role.INSTITUTION, users__is_active=True),
                    distinct=True,
                ),
                institutional_user_count=Count(
                    "users",
                    filter=Q(users__role=User.Role.INSTITUTION),
                    distinct=True,
                ),
                case_count=Count("audit_cases", distinct=True),
            )
            .prefetch_related(
                Prefetch("users", queryset=institutional_accounts, to_attr="institutional_accounts")
            )
        )

    def get_queryset(self):
        queryset = self.center_queryset()
        query = self.request.GET.get("q", "").strip()
        access = self.request.GET.get("access", "")
        if query:
            queryset = queryset.filter(
                Q(code__icontains=query)
                | Q(name__icontains=query)
                | Q(department__icontains=query)
                | Q(municipality__icontains=query)
            )
        if access == "active":
            queryset = queryset.filter(active_user_count__gt=0)
        elif access == "pending":
            queryset = queryset.filter(active_user_count=0)
        return queryset.order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_centers = self.center_queryset()
        context.update(
            {
                "query": self.request.GET.get("q", "").strip(),
                "selected_access": self.request.GET.get("access", ""),
                "total_centers": all_centers.count(),
                "active_centers": all_centers.filter(active_user_count__gt=0).count(),
                "pending_centers": all_centers.filter(active_user_count=0).count(),
            }
        )
        return context


@require_POST
def director_activate_educational_center(request, pk):
    if not user_is_director(request.user):
        raise PermissionDenied("Esta acción es exclusiva de la Dirección de Auditoría.")
    if not request.user.has_usable_password():
        messages.error(request, "No fue posible asignar la credencial inicial al centro.")
        return redirect("director_educational_centers")

    with transaction.atomic():
        center = get_object_or_404(
            Organization.objects.select_for_update(),
            pk=pk,
            kind=Organization.Kind.EDUCATIONAL_CENTER,
        )
        accounts = User.objects.select_for_update().filter(
            organization=center,
            role=User.Role.INSTITUTION,
        )
        active_account = accounts.filter(is_active=True).order_by("username").first()
        if active_account:
            messages.info(
                request,
                f"{center.name} ya tiene acceso activo con el usuario {active_account.username}.",
            )
            return redirect("director_educational_centers")

        account = accounts.order_by("username").first()
        created = account is None
        if created:
            account = User(
                username=institutional_username(center),
                first_name="Responsable",
                last_name="Institucional",
                role=User.Role.INSTITUTION,
                organization=center,
                job_title="Dirección del centro educativo",
                is_staff=False,
            )

        account.is_active = True
        account.must_change_password = False
        # During the pilot all demo users intentionally share the same credential.
        # Copying the encoded value avoids storing or exposing that password in plain text.
        account.password = request.user.password
        account.save()

        center_was_inactive = not center.is_active
        if center_was_inactive:
            center.is_active = True
            center.save(update_fields=["is_active", "updated_at"])

        log_activity(
            request,
            "educational_center_activated",
            target=center,
            details={
                "organization_code": center.code,
                "institutional_user_id": account.pk,
                "username": account.username,
                "account_created": created,
                "organization_reactivated": center_was_inactive,
            },
        )

    messages.success(
        request,
        f"Centro activado. Su nombre de usuario es {account.username} y utiliza la clave común.",
    )
    return redirect("director_educational_centers")


def director_decision_list(request):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    if not user_is_director(request.user):
        raise PermissionDenied("Esta sección es exclusiva de la Dirección de Auditoría.")
    decisions = CaseDecision.objects.select_related(
        "case__audited_organization", "case__assigned_auditor", "requested_by", "decided_by"
    )
    status = request.GET.get("status", CaseDecision.Status.PENDING)
    kind = request.GET.get("kind", "")
    if status in CaseDecision.Status.values:
        decisions = decisions.filter(status=status)
    if kind in CaseDecision.Kind.values:
        decisions = decisions.filter(kind=kind)
    return render(
        request,
        "audits/director_decision_list.html",
        {
            "decisions": decisions,
            "selected_status": status,
            "selected_kind": kind,
            "statuses": CaseDecision.Status.choices,
            "kinds": CaseDecision.Kind.choices,
        },
    )


@transaction.atomic
def director_decision_detail(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    if not user_is_director(request.user):
        raise PermissionDenied("Esta decisión corresponde a la Dirección de Auditoría.")
    decision = get_object_or_404(
        CaseDecision.objects.select_for_update().select_related(
            "case__audited_organization",
            "case__assigned_auditor",
            "document",
            "requested_by",
            "decided_by",
        ),
        pk=pk,
    )
    case = decision.case
    form = DecisionResolutionForm(request.POST or None)
    if request.method == "POST":
        if decision.status != CaseDecision.Status.PENDING:
            messages.info(request, "Esta solicitud ya fue resuelta.")
            return redirect("director_decision_detail", pk=decision.pk)
        if form.is_valid():
            action = form.cleaned_data["action"]
            justification = form.cleaned_data["justification"]
            if action == DecisionResolutionForm.Action.APPROVE:
                if decision.kind == CaseDecision.Kind.PUBLICATION:
                    if case.status != AuditCase.Status.PENDING_PUBLICATION:
                        messages.error(request, "El expediente ya no está pendiente de publicación.")
                        return redirect("director_decision_detail", pk=decision.pk)
                    if publication_issues(case):
                        messages.error(
                            request,
                            "El expediente dejó de reunir los requisitos de publicación.",
                        )
                        return redirect("director_decision_detail", pk=decision.pk)
                    case.status = AuditCase.Status.PUBLISHED
                    if decision.document_id:
                        decision.document.status = AuditDocument.Status.APPROVED
                        decision.document.visibility = AuditDocument.Visibility.INSTITUTION
                        decision.document.save(update_fields=["status", "visibility"])
                    activity_action = "case_publication_approved"
                else:
                    if case.status != AuditCase.Status.PENDING_CLOSURE:
                        messages.error(request, "El expediente ya no está pendiente de cierre.")
                        return redirect("director_decision_detail", pk=decision.pk)
                    if closure_issues(case):
                        messages.error(
                            request,
                            "El expediente ya no reúne las condiciones para el cierre.",
                        )
                        return redirect("director_decision_detail", pk=decision.pk)
                    case.status = AuditCase.Status.CLOSED
                    activity_action = "case_closure_approved"
                decision.status = CaseDecision.Status.APPROVED
                success_message = f"La solicitud de {decision.get_kind_display().lower()} fue aprobada."
            else:
                if decision.kind == CaseDecision.Kind.PUBLICATION:
                    case.status = AuditCase.Status.DRAFT
                    if decision.document_id:
                        decision.document.status = AuditDocument.Status.RETURNED
                        decision.document.visibility = AuditDocument.Visibility.AUDIT_ONLY
                        decision.document.save(update_fields=["status", "visibility"])
                    activity_action = "case_publication_returned"
                else:
                    case.status = decision.previous_case_status or AuditCase.Status.UNDER_REVIEW
                    activity_action = "case_closure_returned"
                decision.status = CaseDecision.Status.RETURNED
                success_message = f"La solicitud de {decision.get_kind_display().lower()} fue devuelta."

            decision.decision_note = justification
            decision.decided_by = request.user
            decision.decided_at = timezone.now()
            case.save(update_fields=["status", "updated_at"])
            decision.save(
                update_fields=["status", "decision_note", "decided_by", "decided_at"]
            )
            log_activity(
                request,
                activity_action,
                case=case,
                target=decision,
                details={"justification": justification},
            )
            messages.success(request, success_message)
            return redirect("director_decisions")
    findings = case.findings.prefetch_related("recommendations__responsible_organization")
    return render(
        request,
        "audits/director_decision_detail.html",
        {"decision": decision, "case": case, "findings": findings, "form": form},
    )


class CaseListView(LoginRequiredMixin, ListView):
    template_name = "audits/case_list.html"
    context_object_name = "cases"
    paginate_by = 20

    def get_queryset(self):
        queryset = accessible_cases(self.request.user)
        search = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        organization_id = self.request.GET.get("organization", "").strip()
        self.selected_organization = None
        self.invalid_organization_filter = False
        if organization_id and self.request.user.is_audit_staff:
            if organization_id.isdigit():
                self.selected_organization = Organization.objects.filter(
                    pk=int(organization_id),
                    kind=Organization.Kind.EDUCATIONAL_CENTER,
                ).first()
            if self.selected_organization:
                queryset = queryset.filter(audited_organization=self.selected_organization)
            else:
                self.invalid_organization_filter = True
                queryset = queryset.none()
        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search)
                | Q(title__icontains=search)
                | Q(audited_organization__name__icontains=search)
                | Q(audited_organization__code__icontains=search)
                | Q(assigned_auditor__username__icontains=search)
                | Q(assigned_auditor__first_name__icontains=search)
                | Q(assigned_auditor__last_name__icontains=search)
            )
        if status in AuditCase.Status.values:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "statuses": AuditCase.Status.choices,
                "selected_organization": self.selected_organization,
                "selected_organization_id": (
                    str(self.selected_organization.pk) if self.selected_organization else ""
                ),
                "invalid_organization_filter": self.invalid_organization_filter,
            }
        )
        return context


@transaction.atomic
def case_create(request):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    if not user_can_create_cases(request.user):
        raise PermissionDenied("Esta acción corresponde al personal auditor autorizado.")
    form = AuditCaseForm(
        request.POST or None,
        request.FILES or None,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        case = form.save(commit=False)
        case.status = AuditCase.Status.DRAFT
        case.created_by = request.user
        if request.user.role == User.Role.AUDITOR:
            case.assigned_auditor = request.user
        case.save()
        log_activity(request, "case_draft_created", case=case, target=case)
        messages.success(request, "El borrador fue creado. Ahora agregue los hallazgos y recomendaciones.")
        return redirect("case_builder", pk=case.pk)
    return render(
        request,
        "audits/case_form.html",
        {"form": form, "case": None, "form_title": "Nuevo expediente"},
    )


@transaction.atomic
def case_edit(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    case = get_editable_case(request.user, pk)
    form = AuditCaseForm(
        request.POST or None,
        request.FILES or None,
        instance=case,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        case = form.save()
        log_activity(request, "case_draft_updated", case=case, target=case)
        messages.success(request, "Los datos generales del expediente fueron actualizados.")
        return redirect("case_builder", pk=case.pk)
    return render(
        request,
        "audits/case_form.html",
        {"form": form, "case": case, "form_title": "Editar datos generales"},
    )


def case_builder(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    case = get_editable_case(request.user, pk)
    findings = case.findings.prefetch_related("recommendations__responsible_organization")
    return render(
        request,
        "audits/case_builder.html",
        {
            "case": case,
            "findings": findings,
            "documents": case.documents.filter(
                document_type=AuditDocument.DocumentType.REPORT
            ).order_by("-version"),
            "publication_issues": publication_issues(case),
        },
    )


@transaction.atomic
def case_report_upload(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    case = get_editable_case(request.user, pk)
    form = CaseReportDocumentForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        uploaded_file = form.cleaned_data["file"]
        document = create_audit_document(
            uploaded_file=uploaded_file,
            user=request.user,
            case=case,
            organization=case.audited_organization,
            document_type=AuditDocument.DocumentType.REPORT,
            reference=form.cleaned_data["reference"],
            title=form.cleaned_data["title"],
            document_date=form.cleaned_data["document_date"],
            version=next_document_version(case, AuditDocument.DocumentType.REPORT),
            status=AuditDocument.Status.DRAFT,
            visibility=AuditDocument.Visibility.AUDIT_ONLY,
        )
        log_activity(request, "case_report_uploaded", case=case, target=document)
        messages.success(request, f"La versión {document.version} del informe fue cargada.")
        return redirect("case_builder", pk=case.pk)
    return render(
        request,
        "audits/case_report_upload.html",
        {"case": case, "form": form},
    )


def historical_document_list(request):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    if not request.user.is_audit_staff:
        raise PermissionDenied("Esta sección corresponde al personal de Auditoría.")

    documents = AuditDocument.objects.filter(
        document_type__in=[
            AuditDocument.DocumentType.REPORT,
            AuditDocument.DocumentType.HISTORICAL_REPORT,
        ]
    ).select_related("case", "organization", "uploaded_by")

    if request.user.role == User.Role.AUDITOR:
        documents = documents.filter(
            Q(document_type=AuditDocument.DocumentType.HISTORICAL_REPORT)
            | Q(
                document_type=AuditDocument.DocumentType.REPORT,
                case__assigned_auditor=request.user,
            )
        )

    search = request.GET.get("q", "").strip()
    organization_id = request.GET.get("organization", "").strip()
    document_type = request.GET.get("type", "").strip()

    if search:
        documents = documents.filter(
            Q(reference__icontains=search)
            | Q(title__icontains=search)
            | Q(organization__name__icontains=search)
            | Q(organization__code__icontains=search)
            | Q(case__reference__icontains=search)
            | Q(case__title__icontains=search)
            | Q(case__findings__recommendations__text__icontains=search)
            | Q(historical_recommendations__text__icontains=search)
        ).distinct()
    if organization_id.isdigit():
        documents = documents.filter(organization_id=organization_id)

    valid_document_types = {
        AuditDocument.DocumentType.REPORT,
        AuditDocument.DocumentType.HISTORICAL_REPORT,
    }
    if document_type in valid_document_types:
        documents = documents.filter(document_type=document_type)
    else:
        document_type = ""

    documents = documents.annotate(
        case_recommendation_count=Count(
            "case__findings__recommendations",
            distinct=True,
        ),
        previous_recommendation_count=Count(
            "historical_recommendations",
            distinct=True,
        ),
    )

    return render(
        request,
        "audits/historical_document_list.html",
        {
            "documents": documents,
            "organizations": Organization.objects.filter(is_active=True).order_by("name"),
            "selected_organization": organization_id,
            "selected_document_type": document_type,
        },
    )


@transaction.atomic
def historical_document_create(request):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    if not request.user.is_audit_staff:
        raise PermissionDenied("Esta acción corresponde al personal de Auditoría.")
    form = HistoricalDocumentForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        uploaded_file = form.cleaned_data["file"]
        document = create_audit_document(
            uploaded_file=uploaded_file,
            user=request.user,
            case=None,
            organization=form.cleaned_data["organization"],
            document_type=AuditDocument.DocumentType.HISTORICAL_REPORT,
            reference=form.cleaned_data["reference"],
            title=form.cleaned_data["title"],
            document_date=form.cleaned_data["document_date"],
            version=1,
            status=AuditDocument.Status.HISTORICAL,
            visibility=AuditDocument.Visibility.INSTITUTION,
        )
        log_activity(request, "historical_document_uploaded", target=document)
        messages.success(
            request,
            "El informe anterior fue registrado. Ahora agregue sus recomendaciones pendientes.",
        )
        return redirect("historical_document_detail", pk=document.pk)
    return render(request, "audits/historical_document_form.html", {"form": form})


def historical_document_detail(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    document = get_object_or_404(
        AuditDocument.objects.select_related("organization", "uploaded_by").prefetch_related(
            "historical_recommendations__responsible_organization"
        ),
        pk=pk,
        document_type=AuditDocument.DocumentType.HISTORICAL_REPORT,
    )
    if not user_can_access_document(request.user, document):
        raise PermissionDenied("No tiene autorización para consultar este documento.")
    return render(
        request,
        "audits/historical_document_detail.html",
        {"document": document},
    )


@transaction.atomic
def historical_recommendation_create(request, document_pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    if not request.user.is_audit_staff:
        raise PermissionDenied("Esta acción corresponde al personal de Auditoría.")
    document = get_object_or_404(
        AuditDocument,
        pk=document_pk,
        document_type=AuditDocument.DocumentType.HISTORICAL_REPORT,
    )
    form = HistoricalRecommendationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        recommendation = form.save(commit=False)
        recommendation.source_document = document
        recommendation.recorded_by = request.user
        recommendation.save()
        log_activity(request, "historical_recommendation_recorded", target=recommendation)
        messages.success(request, "La recomendación fue registrada.")
        return redirect("historical_document_detail", pk=document.pk)
    return render(
        request,
        "audits/historical_recommendation_form.html",
        {"document": document, "form": form},
    )


@transaction.atomic
def case_import_recommendations(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    case = get_editable_case(request.user, pk)
    imported_source_ids = Recommendation.objects.filter(
        finding__case=case,
        source_recommendation__isnull=False,
    ).values_list("source_recommendation_id", flat=True)
    eligible = HistoricalRecommendation.objects.filter(
        source_document__organization=case.audited_organization,
        status__in=[
            HistoricalRecommendation.Status.PARTIAL,
            HistoricalRecommendation.Status.NOT_COMPLIED,
        ],
    ).exclude(pk__in=imported_source_ids).select_related(
        "source_document", "responsible_organization"
    )
    form = HistoricalRecommendationImportForm(
        request.POST or None,
        queryset=eligible,
    )
    if request.method == "POST" and form.is_valid():
        created = copy_historical_recommendations(
            case,
            form.cleaned_data["recommendations"],
        )
        log_activity(
            request,
            "historical_recommendations_imported",
            case=case,
            details={
                "count": len(created),
                "recommendation_ids": [item.pk for item in created],
            },
        )
        messages.success(
            request,
            f"Se incorporaron {len(created)} recomendación"
            f"{'es' if len(created) != 1 else ''} al expediente.",
        )
        return redirect("case_builder", pk=case.pk)
    return render(
        request,
        "audits/case_import_recommendations.html",
        {"case": case, "form": form, "eligible": eligible},
    )


@transaction.atomic
def finding_create(request, case_pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    case = get_editable_case(request.user, case_pk)
    next_number = (case.findings.aggregate(value=Max("number"))["value"] or 0) + 1
    form = FindingForm(request.POST or None, initial={"number": next_number})
    if request.method == "POST" and form.is_valid():
        finding = form.save(commit=False)
        finding.case = case
        finding.save()
        log_activity(request, "finding_created", case=case, target=finding)
        messages.success(request, f"El hallazgo {finding.number} fue agregado.")
        return redirect("case_builder", pk=case.pk)
    return render(
        request,
        "audits/editor_form.html",
        {
            "form": form,
            "case": case,
            "form_title": "Agregar hallazgo",
            "form_intro": "Registre la información que fundamenta el hallazgo.",
            "submit_label": "Guardar hallazgo",
        },
    )


@transaction.atomic
def finding_edit(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    finding = get_object_or_404(Finding.objects.select_related("case"), pk=pk)
    case = get_editable_case(request.user, finding.case_id)
    form = FindingForm(request.POST or None, instance=finding)
    if request.method == "POST" and form.is_valid():
        finding = form.save()
        log_activity(request, "finding_updated", case=case, target=finding)
        messages.success(request, f"El hallazgo {finding.number} fue actualizado.")
        return redirect("case_builder", pk=case.pk)
    return render(
        request,
        "audits/editor_form.html",
        {
            "form": form,
            "case": case,
            "form_title": f"Editar hallazgo {finding.number}",
            "form_intro": "Actualice la información del hallazgo antes de publicar.",
            "submit_label": "Guardar cambios",
        },
    )


@require_POST
@transaction.atomic
def finding_delete(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    finding = get_object_or_404(Finding.objects.select_related("case"), pk=pk)
    case = get_editable_case(request.user, finding.case_id)
    number = finding.number
    log_activity(request, "finding_deleted", case=case, target=finding, details={"number": number})
    finding.delete()
    messages.success(request, f"El hallazgo {number} y sus recomendaciones fueron eliminados.")
    return redirect("case_builder", pk=case.pk)


@transaction.atomic
def recommendation_create(request, finding_pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    finding = get_object_or_404(Finding.objects.select_related("case"), pk=finding_pk)
    case = get_editable_case(request.user, finding.case_id)
    next_number = (finding.recommendations.aggregate(value=Max("number"))["value"] or 0) + 1
    form = RecommendationForm(
        request.POST or None,
        initial={
            "number": next_number,
            "responsible_organization": case.audited_organization_id,
            "deadline": case.response_deadline,
        },
    )
    if request.method == "POST" and form.is_valid():
        recommendation = form.save(commit=False)
        recommendation.finding = finding
        recommendation.save()
        log_activity(request, "recommendation_created", case=case, target=recommendation)
        messages.success(request, f"La recomendación {finding.number}.{recommendation.number} fue agregada.")
        return redirect("case_builder", pk=case.pk)
    return render(
        request,
        "audits/editor_form.html",
        {
            "form": form,
            "case": case,
            "form_title": f"Agregar recomendación al hallazgo {finding.number}",
            "form_intro": "Asigne un responsable, una fecha límite y la evidencia esperada.",
            "submit_label": "Guardar recomendación",
        },
    )


@transaction.atomic
def recommendation_edit(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    recommendation = get_object_or_404(
        Recommendation.objects.select_related("finding__case"), pk=pk
    )
    case = get_editable_case(request.user, recommendation.finding.case_id)
    form = RecommendationForm(request.POST or None, instance=recommendation)
    if request.method == "POST" and form.is_valid():
        recommendation = form.save()
        log_activity(request, "recommendation_updated", case=case, target=recommendation)
        messages.success(
            request,
            f"La recomendación {recommendation.finding.number}.{recommendation.number} fue actualizada.",
        )
        return redirect("case_builder", pk=case.pk)
    return render(
        request,
        "audits/editor_form.html",
        {
            "form": form,
            "case": case,
            "form_title": (
                f"Editar recomendación {recommendation.finding.number}.{recommendation.number}"
            ),
            "form_intro": "Actualice la asignación y los requisitos antes de publicar.",
            "submit_label": "Guardar cambios",
        },
    )


@require_POST
@transaction.atomic
def recommendation_delete(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    recommendation = get_object_or_404(
        Recommendation.objects.select_related("finding__case"), pk=pk
    )
    case = get_editable_case(request.user, recommendation.finding.case_id)
    label = f"{recommendation.finding.number}.{recommendation.number}"
    log_activity(
        request,
        "recommendation_deleted",
        case=case,
        target=recommendation,
        details={"number": label},
    )
    recommendation.delete()
    messages.success(request, f"La recomendación {label} fue eliminada.")
    return redirect("case_builder", pk=case.pk)


@transaction.atomic
def case_publish(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    case = get_object_or_404(
        AuditCase.objects.select_for_update().select_related(
            "audited_organization", "assigned_auditor"
        ),
        pk=pk,
    )
    if not user_can_edit_case(request.user, case):
        raise PermissionDenied("No tiene autorización para enviar este expediente.")
    issues = publication_issues(case)
    findings = case.findings.prefetch_related("recommendations__responsible_organization")
    report_document = case.documents.filter(
        document_type=AuditDocument.DocumentType.REPORT,
        status=AuditDocument.Status.DRAFT,
    ).order_by("-version").first()
    if request.method == "POST":
        if issues:
            messages.error(request, "Complete los requisitos señalados antes de publicar.")
        else:
            decision = CaseDecision.objects.create(
                case=case,
                document=report_document,
                kind=CaseDecision.Kind.PUBLICATION,
                requested_by=request.user,
                previous_case_status=case.status,
            )
            if report_document:
                report_document.status = AuditDocument.Status.PENDING_APPROVAL
                report_document.save(update_fields=["status"])
            case.status = AuditCase.Status.PENDING_PUBLICATION
            case.save(update_fields=["status", "updated_at"])
            log_activity(request, "case_publication_requested", case=case, target=decision)
            messages.success(
                request,
                "El expediente fue enviado a la Dirección de Auditoría para aprobación.",
            )
            return redirect("case_detail", pk=case.pk)
    return render(
        request,
        "audits/case_publish.html",
        {
            "case": case,
            "findings": findings,
            "publication_issues": issues,
            "report_document": report_document,
        },
    )


@transaction.atomic
def request_case_closure(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    case = get_object_or_404(
        AuditCase.objects.select_for_update().select_related(
            "audited_organization", "assigned_auditor"
        ),
        pk=pk,
    )
    if request.user.role != User.Role.AUDITOR or case.assigned_auditor_id != request.user.pk:
        raise PermissionDenied("Solo el auditor asignado puede solicitar el cierre.")
    if case.status in {
        AuditCase.Status.DRAFT,
        AuditCase.Status.PENDING_PUBLICATION,
        AuditCase.Status.PENDING_CLOSURE,
        AuditCase.Status.CLOSED,
    }:
        raise PermissionDenied("El expediente no admite una solicitud de cierre en su estado actual.")
    issues = closure_issues(case)
    form = ClosureRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if issues:
            messages.error(request, "Complete la revisión de las recomendaciones antes de solicitar el cierre.")
        else:
            previous_status = case.status
            decision = CaseDecision.objects.create(
                case=case,
                kind=CaseDecision.Kind.CLOSURE,
                request_note=form.cleaned_data["justification"],
                previous_case_status=previous_status,
                requested_by=request.user,
            )
            case.status = AuditCase.Status.PENDING_CLOSURE
            case.save(update_fields=["status", "updated_at"])
            log_activity(
                request,
                "case_closure_requested",
                case=case,
                target=decision,
                details={"justification": form.cleaned_data["justification"]},
            )
            messages.success(request, "La solicitud de cierre fue enviada a la Dirección de Auditoría.")
            return redirect("case_detail", pk=case.pk)
    return render(
        request,
        "audits/case_closure_request.html",
        {"case": case, "form": form, "closure_issues": issues},
    )


@transaction.atomic
def director_reassign_case(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    if not user_is_director(request.user):
        raise PermissionDenied("La reasignación corresponde a la Dirección de Auditoría.")
    case = get_object_or_404(
        AuditCase.objects.select_for_update().select_related(
            "audited_organization", "assigned_auditor"
        ),
        pk=pk,
    )
    if case.status == AuditCase.Status.CLOSED:
        raise PermissionDenied("Un expediente cerrado no puede reasignarse.")
    previous_auditor = case.assigned_auditor
    form = AuditorReassignmentForm(
        request.POST or None,
        current_auditor=previous_auditor,
    )
    if request.method == "POST" and form.is_valid():
        new_auditor = form.cleaned_data["assigned_auditor"]
        justification = form.cleaned_data["justification"]
        case.assigned_auditor = new_auditor
        case.save(update_fields=["assigned_auditor", "updated_at"])
        log_activity(
            request,
            "case_reassigned",
            case=case,
            target=case,
            details={
                "previous_auditor_id": previous_auditor.pk,
                "previous_auditor": previous_auditor.get_full_name() or previous_auditor.username,
                "new_auditor_id": new_auditor.pk,
                "new_auditor": new_auditor.get_full_name() or new_auditor.username,
                "justification": justification,
            },
        )
        messages.success(request, "El expediente fue reasignado y la decisión quedó registrada.")
        return redirect("case_detail", pk=case.pk)
    return render(
        request,
        "audits/director_reassign_case.html",
        {"case": case, "form": form, "previous_auditor": previous_auditor},
    )


def case_detail(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    case = get_accessible_case(request.user, pk)
    visible_responses = Response.objects.select_related(
        "review",
        "school_board_period__organization",
    ).prefetch_related("evidence")
    if request.user.role == User.Role.INSTITUTION:
        visible_responses = visible_responses.filter(
            recommendation__responsible_organization_id=request.user.organization_id
        )
    findings = case.findings.prefetch_related(
        "recommendations__responsible_organization",
        "recommendations__source_recommendation__source_document",
        "recommendations__deadline_extensions__granted_by",
        Prefetch(
            "recommendations__responses",
            queryset=visible_responses,
            to_attr="visible_responses",
        ),
    )
    documents = case.documents.select_related("uploaded_by")
    if request.user.role == User.Role.INSTITUTION:
        documents = documents.filter(
            organization_id=request.user.organization_id,
            visibility=AuditDocument.Visibility.INSTITUTION,
            status=AuditDocument.Status.APPROVED,
        )
    return render(
        request,
        "audits/case_detail.html",
        {
            "case": case,
            "findings": findings,
            "documents": documents,
            "can_edit_case": user_can_edit_case(request.user, case),
            "can_request_closure": (
                request.user.role == User.Role.AUDITOR
                and case.assigned_auditor_id == request.user.pk
                and case.status
                not in {
                    AuditCase.Status.DRAFT,
                    AuditCase.Status.PENDING_PUBLICATION,
                    AuditCase.Status.PENDING_CLOSURE,
                    AuditCase.Status.CLOSED,
                }
            ),
            "closure_issues": closure_issues(case),
            "pending_decision": case.decisions.filter(
                status=CaseDecision.Status.PENDING
            ).first(),
            "can_reassign_case": user_is_director(request.user)
            and case.status != AuditCase.Status.CLOSED,
        },
    )


@transaction.atomic
def grant_deadline_extension(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    recommendation = get_object_or_404(
        Recommendation.objects.select_for_update().select_related(
            "finding__case__audited_organization"
        ),
        pk=pk,
    )
    case = recommendation.finding.case
    can_grant = user_is_director(request.user) or (
        request.user.role == User.Role.AUDITOR
        and case.assigned_auditor_id == request.user.pk
    )
    if not can_grant:
        raise PermissionDenied("Solo Auditoría puede registrar una prórroga.")
    if case.status == AuditCase.Status.CLOSED or recommendation.status not in {
        Recommendation.Status.PENDING,
        Recommendation.Status.CORRECTION_REQUIRED,
    }:
        raise PermissionDenied("Esta recomendación no admite una prórroga.")
    if not recommendation.deadline:
        messages.error(request, "La recomendación no tiene una fecha límite inicial.")
        return redirect("case_detail", pk=case.pk)

    form = DeadlineExtensionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        previous_deadline = recommendation.deadline
        new_deadline = add_business_days(
            previous_deadline,
            form.cleaned_data["business_days"],
        )
        extension = form.save(commit=False)
        extension.recommendation = recommendation
        extension.previous_deadline = previous_deadline
        extension.new_deadline = new_deadline
        extension.granted_by = request.user
        extension.save()
        recommendation.deadline = new_deadline
        recommendation.save(update_fields=["deadline"])
        log_activity(
            request,
            "recommendation_deadline_extended",
            case=case,
            target=extension,
            details={
                "previous_deadline": previous_deadline.isoformat(),
                "new_deadline": new_deadline.isoformat(),
                "business_days": extension.business_days,
                "reason": extension.reason,
            },
        )
        messages.success(
            request,
            f"La fecha límite fue prorrogada hasta el {new_deadline:%d/%m/%Y}.",
        )
        return redirect("case_detail", pk=case.pk)
    return render(
        request,
        "audits/deadline_extension_form.html",
        {"case": case, "recommendation": recommendation, "form": form},
    )


def download_audit_document(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    document = get_object_or_404(
        AuditDocument.objects.select_related("case__assigned_auditor", "organization"),
        pk=pk,
    )
    if not user_can_access_document(request.user, document):
        raise PermissionDenied("No tiene autorización para descargar este documento.")
    log_activity(
        request,
        "audit_document_downloaded",
        case=document.case,
        target=document,
    )
    return FileResponse(
        document.file.open("rb"),
        as_attachment=True,
        filename=document.original_filename,
    )


def download_report(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    case = get_accessible_case(request.user, pk)
    document_statuses = [
        AuditDocument.Status.APPROVED,
        AuditDocument.Status.PENDING_APPROVAL,
        AuditDocument.Status.DRAFT,
        AuditDocument.Status.RETURNED,
    ]
    if request.user.role == User.Role.INSTITUTION:
        document_statuses = [AuditDocument.Status.APPROVED]
    document = case.documents.filter(
        document_type=AuditDocument.DocumentType.REPORT,
        status__in=document_statuses,
    ).order_by("-version").first()
    if document:
        if not user_can_access_document(request.user, document):
            raise PermissionDenied("No tiene autorización para descargar este informe.")
        log_activity(request, "report_downloaded", case=case, target=document)
        return FileResponse(
            document.file.open("rb"),
            as_attachment=True,
            filename=document.original_filename,
        )
    if not case.report_file:
        raise Http404("Este expediente no tiene un informe adjunto.")
    log_activity(request, "report_downloaded", case=case, target=case)
    return FileResponse(
        case.report_file.open("rb"),
        as_attachment=True,
        filename=f"{case.reference}.pdf",
    )


@transaction.atomic
def respond_recommendation(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    recommendation = get_object_or_404(
        Recommendation.objects.select_related("finding__case", "responsible_organization"), pk=pk
    )
    case = recommendation.finding.case
    if case.status in {
        AuditCase.Status.DRAFT,
        AuditCase.Status.PENDING_PUBLICATION,
        AuditCase.Status.PENDING_CLOSURE,
        AuditCase.Status.CLOSED,
    }:
        raise Http404("La recomendación aún no ha sido publicada.")
    if (
        request.user.role != User.Role.INSTITUTION
        or not request.user.organization_id
        or recommendation.responsible_organization_id != request.user.organization_id
    ):
        raise PermissionDenied("No tiene autorización para responder esta recomendación.")
    if recommendation.status not in {
        Recommendation.Status.PENDING,
        Recommendation.Status.CORRECTION_REQUIRED,
    }:
        messages.info(request, "Esta recomendación no admite una respuesta nueva en su estado actual.")
        return redirect("case_detail", pk=case.pk)

    if request.method == "POST":
        form = ResponseForm(request.POST, request.FILES)
        if form.is_valid():
            latest_version = recommendation.responses.aggregate(value=Max("version"))["value"] or 0
            response = form.save(commit=False)
            response.recommendation = recommendation
            response.version = latest_version + 1
            response.submitted_by = request.user
            response.school_board_period = SchoolBoardPeriod.objects.filter(
                organization=recommendation.responsible_organization,
                is_current=True,
            ).first()
            response.save()

            for uploaded_file in form.cleaned_data["files"]:
                digest = hashlib.sha256()
                for chunk in uploaded_file.chunks():
                    digest.update(chunk)
                uploaded_file.seek(0)
                Evidence.objects.create(
                    response=response,
                    file=uploaded_file,
                    original_filename=uploaded_file.name[:255],
                    category=form.cleaned_data["evidence_category"],
                    description=form.cleaned_data["evidence_description"],
                    size=uploaded_file.size,
                    sha256=digest.hexdigest(),
                    scan_status=(
                        Evidence.ScanStatus.PENDING
                        if settings.FILE_SCAN_REQUIRED
                        else Evidence.ScanStatus.CLEAN
                    ),
                    uploaded_by=request.user,
                )

            recommendation.status = Recommendation.Status.SUBMITTED
            recommendation.save(update_fields=["status"])
            if case.status != AuditCase.Status.CLOSED:
                case.status = AuditCase.Status.UNDER_REVIEW
                case.save(update_fields=["status", "updated_at"])
            log_activity(
                request,
                "response_submitted",
                case=case,
                target=response,
                details={
                    "recommendation": recommendation.pk,
                    "version": response.version,
                    "school_board_period_id": response.school_board_period_id,
                },
            )
            messages.success(request, "La respuesta fue enviada y quedó registrada en el expediente.")
            return redirect("case_detail", pk=case.pk)
    else:
        form = ResponseForm(
            initial={
                "responsible_name": request.user.get_full_name(),
                "responsible_job_title": request.user.job_title,
            }
        )
    return render(
        request,
        "audits/respond.html",
        {"form": form, "recommendation": recommendation, "case": case},
    )


@transaction.atomic
def review_response(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    if request.user.role not in {User.Role.AUDITOR, User.Role.AUDIT_MANAGER}:
        raise PermissionDenied("Esta acción corresponde al personal de Auditoría.")
    response = get_object_or_404(
        Response.objects.select_related("recommendation__finding__case", "submitted_by"), pk=pk
    )
    get_accessible_case(request.user, response.recommendation.finding.case_id)
    if hasattr(response, "review"):
        messages.info(request, "Esta versión ya fue revisada.")
        return redirect("case_detail", pk=response.recommendation.finding.case_id)
    if request.method == "POST":
        form = ReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.response = response
            review.reviewed_by = request.user
            review.save()
            recommendation = response.recommendation
            recommendation.status = {
                Review.Outcome.CORRECTION_REQUIRED: Recommendation.Status.CORRECTION_REQUIRED,
                Review.Outcome.COMPLIED: Recommendation.Status.COMPLIED,
                Review.Outcome.PARTIAL: Recommendation.Status.PARTIAL,
                Review.Outcome.NOT_COMPLIED: Recommendation.Status.NOT_COMPLIED,
            }[review.outcome]
            recommendation.save(update_fields=["status"])
            case = recommendation.finding.case
            if review.outcome == Review.Outcome.CORRECTION_REQUIRED:
                case.status = AuditCase.Status.CORRECTION_REQUIRED
                case.save(update_fields=["status", "updated_at"])
            log_activity(
                request,
                "response_reviewed",
                case=case,
                target=review,
                details={"outcome": review.outcome, "response": response.pk},
            )
            messages.success(request, "La revisión fue registrada correctamente.")
            return redirect("case_detail", pk=case.pk)
    else:
        form = ReviewForm()
    return render(request, "audits/review.html", {"form": form, "response": response})


def download_evidence(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    evidence = get_object_or_404(
        Evidence.objects.select_related("response__recommendation__finding__case"), pk=pk
    )
    case = evidence.response.recommendation.finding.case
    get_accessible_case(request.user, case.pk)
    if not user_can_access_response(request.user, evidence.response):
        raise PermissionDenied("No tiene autorización para descargar esta evidencia.")
    if settings.FILE_SCAN_REQUIRED and evidence.scan_status != Evidence.ScanStatus.CLEAN:
        raise Http404("La evidencia aún no está disponible.")
    log_activity(request, "evidence_downloaded", case=case, target=evidence)
    return FileResponse(
        evidence.file.open("rb"),
        as_attachment=True,
        filename=evidence.original_filename,
    )


def response_receipt(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"/ingresar/?next={request.path}")
    response = get_object_or_404(
        Response.objects.select_related(
            "recommendation__finding__case__audited_organization",
            "recommendation__responsible_organization",
        ).prefetch_related("evidence"),
        pk=pk,
    )
    case = response.recommendation.finding.case
    get_accessible_case(request.user, case.pk)
    if not user_can_access_response(request.user, response):
        raise PermissionDenied("No tiene autorización para descargar esta constancia.")
    pdf_buffer, folio = build_response_receipt(response)
    log_activity(request, "response_receipt_downloaded", case=case, target=response, details={"folio": folio})
    return FileResponse(pdf_buffer, as_attachment=True, filename=f"{folio}.pdf")
