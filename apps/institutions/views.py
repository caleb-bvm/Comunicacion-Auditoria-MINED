from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.models import User
from apps.audits.models import ActivityLog, AuditCase
from apps.core.scanning import protected_file_response

from .forms import (
    SchoolBoardMemberDepartureForm,
    SchoolBoardMemberForm,
    SchoolBoardPeriodCorrectionForm,
    SchoolBoardPeriodForm,
)
from .models import Organization, SchoolBoardMember, SchoolBoardPeriod


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")


def _log_cde_activity(request, action, target, organization, summary, details=None):
    payload = {
        "organization_id": organization.pk,
        "organization_code": organization.code,
        "summary": summary,
    }
    payload.update(details or {})
    ActivityLog.objects.create(
        actor=request.user,
        action=action,
        target_type=target.__class__.__name__,
        target_id=str(target.pk),
        details=payload,
        ip_address=_client_ip(request),
    )


def _can_manage_cde(user, organization):
    return bool(
        user.is_authenticated
        and user.role == User.Role.INSTITUTION
        and user.organization_id == organization.pk
    )


def _can_view_cde(user, organization):
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.role == User.Role.AUDIT_MANAGER:
        return True
    if _can_manage_cde(user, organization):
        return True
    if user.role == User.Role.AUDITOR:
        return AuditCase.objects.filter(
            audited_organization=organization,
            assigned_auditor=user,
        ).exists()
    return False


def _educational_center(pk):
    return get_object_or_404(
        Organization,
        pk=pk,
        kind=Organization.Kind.EDUCATIONAL_CENTER,
    )


def _require_cde_view(user, organization):
    if not _can_view_cde(user, organization):
        raise PermissionDenied("No tiene autorización para consultar el CDE de este centro.")


def _require_cde_management(user, organization):
    if not _can_manage_cde(user, organization):
        raise PermissionDenied("El CDE solamente puede ser actualizado por el propio centro educativo.")


def _period_snapshot(period):
    return {
        "start_date": period.start_date.isoformat(),
        "end_date": period.end_date.isoformat(),
        "school_year_start": period.school_year_start,
        "school_year_end": period.school_year_end,
        "supporting_document_name": period.supporting_document_name,
        "notes": period.notes,
    }


def _member_snapshot(member):
    return {
        "full_name": member.full_name,
        "identity_document": member.identity_document,
        "position": member.position,
        "sector": member.sector,
        "is_legal_representative": member.is_legal_representative,
        "joined_on": member.joined_on.isoformat(),
        "left_on": member.left_on.isoformat() if member.left_on else None,
        "exit_reason": member.exit_reason,
        "change_document_name": member.change_document_name,
    }


@login_required
def cde_home(request):
    if request.user.role != User.Role.INSTITUTION or not request.user.organization_id:
        raise PermissionDenied("Esta sección corresponde a las cuentas institucionales.")
    return redirect("cde_detail", organization_pk=request.user.organization_id)


@login_required
def cde_detail(request, organization_pk):
    organization = _educational_center(organization_pk)
    _require_cde_view(request.user, organization)
    periods = list(organization.school_board_periods.prefetch_related("members").all())
    for period in periods:
        active_members = [member for member in period.members.all() if member.is_active]
        period.active_member_count = len(active_members)
        period.legal_representative_count = sum(
            member.is_legal_representative for member in active_members
        )
    activity = ActivityLog.objects.filter(
        action__startswith="cde_",
        details__organization_id=organization.pk,
    ).select_related("actor")[:30]
    return render(
        request,
        "institutions/cde_detail.html",
        {
            "organization": organization,
            "periods": periods,
            "current_period": next((period for period in periods if period.is_current), None),
            "can_manage": _can_manage_cde(request.user, organization),
            "activity": activity,
        },
    )


@login_required
def cde_period_create(request, organization_pk):
    organization = _educational_center(organization_pk)
    _require_cde_management(request.user, organization)
    form = SchoolBoardPeriodForm(request.POST or None, request.FILES or None)
    form.instance.organization = organization
    form.instance.created_by = request.user
    form.instance.updated_by = request.user
    if request.method == "POST" and form.is_valid():
        uploaded_document = form.cleaned_data["supporting_document"]
        with transaction.atomic():
            previous_periods = list(
                SchoolBoardPeriod.objects.select_for_update().filter(
                    organization=organization,
                    is_current=True,
                )
            )
            SchoolBoardPeriod.objects.filter(pk__in=[item.pk for item in previous_periods]).update(
                is_current=False,
                updated_by=request.user,
                updated_at=timezone.now(),
            )
            period = form.save(commit=False)
            period.supporting_document_name = Path(uploaded_document.name).name
            period.is_current = True
            period.save()
            _log_cde_activity(
                request,
                "cde_period_created",
                period,
                organization,
                (
                    f"Se registró el CDE {period.school_year_start}-"
                    f"{period.school_year_end} como período vigente."
                ),
                {"previous_period_ids": [item.pk for item in previous_periods]},
            )
        messages.success(request, "El nuevo período del CDE quedó registrado.")
        return redirect("cde_detail", organization_pk=organization.pk)
    return render(
        request,
        "institutions/cde_form.html",
        {
            "form": form,
            "organization": organization,
            "title": "Registrar período del CDE",
            "eyebrow": "Consejo Directivo Escolar",
            "intro": (
                "El período vigente anterior se conservará como finalizado cuando registre este CDE."
            ),
            "submit_label": "Registrar período",
        },
    )


@login_required
def cde_period_edit(request, pk):
    period = get_object_or_404(SchoolBoardPeriod.objects.select_related("organization"), pk=pk)
    organization = period.organization
    _require_cde_management(request.user, organization)
    before = _period_snapshot(period)
    form = SchoolBoardPeriodCorrectionForm(request.POST or None, instance=period)
    if request.method == "POST" and form.is_valid():
        updated = form.save(commit=False)
        updated.updated_by = request.user
        updated.save()
        _log_cde_activity(
            request,
            "cde_period_corrected",
            updated,
            organization,
            f"Se corrigieron los datos del CDE {updated.school_year_start}-{updated.school_year_end}.",
            {"before": before, "after": _period_snapshot(updated)},
        )
        messages.success(request, "Los datos del período fueron corregidos y el cambio quedó en bitácora.")
        return redirect("cde_detail", organization_pk=organization.pk)
    return render(
        request,
        "institutions/cde_form.html",
        {
            "form": form,
            "organization": organization,
            "title": "Corregir período del CDE",
            "eyebrow": "Consejo Directivo Escolar",
            "intro": "Los valores anteriores y los nuevos quedarán registrados.",
            "submit_label": "Guardar corrección",
        },
    )


@login_required
def cde_member_create(request, period_pk):
    period = get_object_or_404(SchoolBoardPeriod.objects.select_related("organization"), pk=period_pk)
    organization = period.organization
    _require_cde_management(request.user, organization)
    form = SchoolBoardMemberForm(
        request.POST or None,
        initial={"joined_on": period.start_date},
    )
    form.instance.period = period
    form.instance.created_by = request.user
    form.instance.updated_by = request.user
    if request.method == "POST" and form.is_valid():
        member = form.save()
        _log_cde_activity(
            request,
            "cde_member_added",
            member,
            organization,
            f"Se incorporó a {member.full_name} como {member.position}.",
            {"period_id": period.pk, "member": _member_snapshot(member)},
        )
        messages.success(request, "El integrante fue incorporado al CDE.")
        return redirect("cde_detail", organization_pk=organization.pk)
    return render(
        request,
        "institutions/cde_form.html",
        {
            "form": form,
            "organization": organization,
            "title": "Agregar integrante",
            "eyebrow": f"CDE {period.school_year_start}-{period.school_year_end}",
            "intro": "Registre a la persona, su cargo y el sector que representa.",
            "submit_label": "Agregar integrante",
        },
    )


@login_required
def cde_member_edit(request, pk):
    member = get_object_or_404(
        SchoolBoardMember.objects.select_related("period__organization"),
        pk=pk,
    )
    organization = member.period.organization
    _require_cde_management(request.user, organization)
    before = _member_snapshot(member)
    form = SchoolBoardMemberForm(request.POST or None, instance=member)
    if request.method == "POST" and form.is_valid():
        updated = form.save(commit=False)
        updated.updated_by = request.user
        updated.save()
        _log_cde_activity(
            request,
            "cde_member_corrected",
            updated,
            organization,
            f"Se corrigieron los datos de {updated.full_name}.",
            {"before": before, "after": _member_snapshot(updated)},
        )
        messages.success(request, "Los datos del integrante fueron corregidos y registrados en bitácora.")
        return redirect("cde_detail", organization_pk=organization.pk)
    return render(
        request,
        "institutions/cde_form.html",
        {
            "form": form,
            "organization": organization,
            "title": "Corregir integrante",
            "eyebrow": "Consejo Directivo Escolar",
            "intro": "La salida o sustitución se registra mediante una acción separada.",
            "submit_label": "Guardar corrección",
        },
    )


@login_required
def cde_member_departure(request, pk):
    member = get_object_or_404(
        SchoolBoardMember.objects.select_related("period__organization"),
        pk=pk,
    )
    organization = member.period.organization
    _require_cde_management(request.user, organization)
    if member.left_on:
        messages.info(request, "La salida de este integrante ya fue registrada.")
        return redirect("cde_detail", organization_pk=organization.pk)
    form = SchoolBoardMemberDepartureForm(request.POST or None, request.FILES or None, instance=member)
    if request.method == "POST" and form.is_valid():
        uploaded_document = form.cleaned_data.get("change_document")
        updated = form.save(commit=False)
        if uploaded_document and hasattr(uploaded_document, "name"):
            updated.change_document_name = Path(uploaded_document.name).name
        updated.updated_by = request.user
        updated.save()
        _log_cde_activity(
            request,
            "cde_member_departed",
            updated,
            organization,
            f"Se registró la salida de {updated.full_name} con fecha {updated.left_on:%d/%m/%Y}.",
            {"period_id": updated.period_id, "member": _member_snapshot(updated)},
        )
        messages.success(request, "La salida quedó registrada sin eliminar al integrante del historial.")
        return redirect("cde_detail", organization_pk=organization.pk)
    return render(
        request,
        "institutions/cde_form.html",
        {
            "form": form,
            "organization": organization,
            "title": f"Registrar salida de {member.full_name}",
            "eyebrow": "Salida o sustitución",
            "intro": "El integrante permanecerá visible dentro del historial de este período.",
            "submit_label": "Registrar salida",
        },
    )


@login_required
def cde_period_document(request, pk):
    period = get_object_or_404(SchoolBoardPeriod.objects.select_related("organization"), pk=pk)
    _require_cde_view(request.user, period.organization)
    if not period.supporting_document:
        raise Http404("El período no tiene un documento asociado.")
    return protected_file_response(
        period.supporting_document.open("rb"),
        as_attachment=True,
        filename=period.supporting_document_name or Path(period.supporting_document.name).name,
    )


@login_required
def cde_member_document(request, pk):
    member = get_object_or_404(
        SchoolBoardMember.objects.select_related("period__organization"),
        pk=pk,
    )
    _require_cde_view(request.user, member.period.organization)
    if not member.change_document:
        raise Http404("El integrante no tiene un documento de cambio asociado.")
    return protected_file_response(
        member.change_document.open("rb"),
        as_attachment=True,
        filename=member.change_document_name or Path(member.change_document.name).name,
    )
