"""Biblioteca de hallazgos y recomendaciones estándar.

Dirección mantiene las áreas auditadas y las plantillas; el personal auditor las copia a
sus borradores. Nada se elimina: áreas y plantillas se desactivan."""

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import FindingCategoryForm, FindingTemplateForm, RecommendationTemplateFormSet
from .models import Finding, FindingCategory, FindingTemplate
from .services import (
    create_finding_from_finding,
    create_finding_from_template,
    create_template_from_finding,
)
from .views import get_editable_case, log_activity, require_director

TEMPLATE_PAGE_SIZE = 25


def login_redirect(request):
    return redirect(f"/ingresar/?next={request.path}")


def filtered_templates(request, queryset):
    query = request.GET.get("q", "").strip()
    category = request.GET.get("area", "").strip()
    if query:
        queryset = queryset.filter(
            Q(title__icontains=query)
            | Q(condition__icontains=query)
            | Q(recommendations__text__icontains=query)
        ).distinct()
    if category.isdigit():
        queryset = queryset.filter(category_id=int(category))
    return queryset, query, category


# ---------- Dirección ----------


def save_recommendation_templates(formset, template):
    """Guarda las recomendaciones de la plantilla numerándolas en el orden del formulario."""
    kept = []
    for form in formset.forms:
        if not form.has_changed() and not form.instance.pk:
            continue
        if formset.can_delete and formset._should_delete_form(form):
            if form.instance.pk:
                form.instance.delete()
            continue
        item = form.save(commit=False)
        item.finding_template = template
        kept.append(item)
    # Mueve temporalmente los números existentes para no chocar con la restricción única.
    template.recommendations.update(number=F("number") + 1000)
    for number, item in enumerate(kept, start=1):
        item.number = number
        item.save()


def director_library(request):
    if not request.user.is_authenticated:
        return login_redirect(request)
    require_director(request.user)
    templates = FindingTemplate.objects.select_related("category").annotate(
        recommendation_count=Count("recommendations", distinct=True),
        use_count=Count("findings", distinct=True),
    )
    status = request.GET.get("estado", "active")
    if status == "active":
        templates = templates.filter(is_active=True)
    elif status == "inactive":
        templates = templates.filter(is_active=False)
    templates, query, category = filtered_templates(request, templates)
    page = Paginator(templates.order_by("category__name", "title"), TEMPLATE_PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    categories = FindingCategory.objects.annotate(
        template_count=Count("templates", filter=Q(templates__is_active=True), distinct=True),
        finding_count=Count("findings", distinct=True),
    )
    return render(
        request,
        "audits/library_list.html",
        {
            "page_obj": page,
            "templates": page.object_list,
            "categories": categories,
            "active_categories": [item for item in categories if item.is_active],
            "query": query,
            "selected_category": category,
            "selected_status": status,
        },
    )


def director_library_category_form(request, pk=None):
    if not request.user.is_authenticated:
        return login_redirect(request)
    require_director(request.user)
    category = get_object_or_404(FindingCategory, pk=pk) if pk else None
    form = FindingCategoryForm(request.POST or None, instance=category)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            saved = form.save()
            log_activity(
                request,
                "library_category_updated" if category else "library_category_created",
                target=saved,
                details={"name": saved.name, "is_active": saved.is_active},
            )
        messages.success(request, f"El área «{saved.name}» fue guardada.")
        return redirect("director_library")
    return render(
        request,
        "audits/library_form.html",
        {
            "form": form,
            "page_title": "Editar área auditada" if category else "Nueva área auditada",
            "page_context": "Clasifica hallazgos y plantillas de la biblioteca.",
            "submit_label": "Guardar área",
        },
    )


def director_library_template_form(request, pk=None):
    if not request.user.is_authenticated:
        return login_redirect(request)
    require_director(request.user)
    template = get_object_or_404(FindingTemplate, pk=pk) if pk else None
    form = FindingTemplateForm(request.POST or None, instance=template)
    formset = RecommendationTemplateFormSet(
        request.POST or None, instance=template or FindingTemplate(), prefix="recomendaciones"
    )
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            saved = form.save(commit=False)
            if not template:
                saved.created_by = request.user
            saved.save()
            formset.instance = saved
            save_recommendation_templates(formset, saved)
            log_activity(
                request,
                "library_template_updated" if template else "library_template_created",
                target=saved,
                details={"title": saved.title, "is_active": saved.is_active},
            )
        messages.success(request, "La plantilla fue guardada.")
        return redirect("director_library")
    return render(
        request,
        "audits/library_form.html",
        {
            "form": form,
            "formset": formset,
            "template_obj": template,
            "page_title": "Editar plantilla" if template else "Nueva plantilla",
            "page_context": "Hallazgo estándar con sus recomendaciones. Los auditores lo copian a sus borradores y lo adaptan.",
            "submit_label": "Guardar plantilla",
        },
    )


@require_POST
def director_library_from_finding(request, pk):
    if not request.user.is_authenticated:
        return login_redirect(request)
    require_director(request.user)
    finding = get_object_or_404(Finding.objects.select_related("case"), pk=pk)
    template = create_template_from_finding(finding, request.user)
    log_activity(
        request,
        "library_template_from_finding",
        case=finding.case,
        target=template,
        details={"finding": finding.number},
    )
    messages.success(
        request,
        "Se creó una plantilla inactiva a partir del hallazgo. Generalice los datos propios del "
        "caso (use [corchetes]) y actívela para ofrecerla a los auditores.",
    )
    return redirect("director_library_template_edit", pk=template.pk)


# ---------- Personal auditor ----------


def case_library(request, pk):
    if not request.user.is_authenticated:
        return login_redirect(request)
    case = get_editable_case(request.user, pk)
    templates = (
        FindingTemplate.objects.filter(is_active=True)
        .select_related("category")
        .prefetch_related("recommendations")
    )
    templates, query, category = filtered_templates(request, templates)
    page = Paginator(templates.order_by("category__name", "title"), TEMPLATE_PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    return render(
        request,
        "audits/case_library.html",
        {
            "case": case,
            "page_obj": page,
            "templates": page.object_list,
            "categories": FindingCategory.objects.filter(is_active=True),
            "query": query,
            "selected_category": category,
        },
    )


@require_POST
def case_library_use(request, pk, template_pk):
    if not request.user.is_authenticated:
        return login_redirect(request)
    case = get_editable_case(request.user, pk)
    template = get_object_or_404(FindingTemplate, pk=template_pk, is_active=True)
    finding = create_finding_from_template(case, template)
    log_activity(
        request,
        "finding_created_from_template",
        case=case,
        target=finding,
        details={"template": template.pk, "number": finding.number},
    )
    count = finding.recommendations.count()
    messages.success(
        request,
        f"Se agregó el hallazgo {finding.number} con {count} "
        f"recomendaci{'ón' if count == 1 else 'ones'}. Adapte el texto al caso y complete "
        "los datos entre [corchetes].",
    )
    return redirect("finding_edit", pk=finding.pk)


def own_previous_findings(user, case):
    """Hallazgos de otros expedientes asignados al mismo auditor (nunca de otros auditores)."""
    return (
        Finding.objects.filter(case__assigned_auditor=user)
        .exclude(case=case)
        .select_related("case__audited_organization", "category")
        .prefetch_related("recommendations")
    )


def case_copy_previous(request, pk):
    if not request.user.is_authenticated:
        return login_redirect(request)
    case = get_editable_case(request.user, pk)
    findings = own_previous_findings(request.user, case)
    query = request.GET.get("q", "").strip()
    if query:
        findings = findings.filter(
            Q(title__icontains=query)
            | Q(condition__icontains=query)
            | Q(case__reference__icontains=query)
            | Q(case__audited_organization__name__icontains=query)
        )
    page = Paginator(findings.order_by("-case__created_at", "number"), TEMPLATE_PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    return render(
        request,
        "audits/case_copy_finding.html",
        {"case": case, "page_obj": page, "findings": page.object_list, "query": query},
    )


@require_POST
def case_copy_previous_use(request, pk, finding_pk):
    if not request.user.is_authenticated:
        return login_redirect(request)
    case = get_editable_case(request.user, pk)
    source = get_object_or_404(own_previous_findings(request.user, case), pk=finding_pk)
    finding = create_finding_from_finding(case, source)
    log_activity(
        request,
        "finding_copied_from_case",
        case=case,
        target=finding,
        details={"source_case": source.case.reference, "source_finding": source.number},
    )
    messages.success(
        request,
        f"Se copió el hallazgo {source.number} de {source.case.reference} como hallazgo "
        f"{finding.number}. Actualice los hechos, cifras y fechas para este expediente.",
    )
    return redirect("finding_edit", pk=finding.pk)
