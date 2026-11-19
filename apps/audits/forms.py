from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.db import models

from apps.accounts.models import User
from apps.institutions.models import Organization

from apps.core.validators import EVIDENCE_ACCEPT, validate_evidence_file
from apps.core.widgets import FastSelect, DateInput, OrganizationSearchSelect

from .snippets import (
    EVIDENCE_SNIPPETS,
    FINDING_SNIPPETS,
    LINE,
    RECOMMENDATION_SNIPPETS,
    build_snippets,
)
from .models import (
    AuditCase,
    AuditDocument,
    AuditInquiry,
    DeadlineExtension,
    Evidence,
    Finding,
    FindingCategory,
    FindingTemplate,
    HistoricalRecommendation,
    Recommendation,
    RecommendationTemplate,
    Response,
    Review,
)


class AuditInquiryCreateForm(forms.ModelForm):
    body = forms.CharField(
        label="Detalle de la consulta",
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Describa la duda y el resultado que necesita obtener.",
    )
    attachment = forms.FileField(
        label="Archivo de respaldo", required=False,
        validators=[validate_evidence_file],
        widget=forms.ClearableFileInput(attrs={"accept": EVIDENCE_ACCEPT}),
        help_text="Opcional. PDF, imagen, Word o Excel.",
    )

    class Meta:
        model = AuditInquiry
        fields = ("case", "category", "subject", "priority", "body", "attachment")

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["case"].queryset = AuditCase.objects.none()
        if user and user.role == User.Role.INSTITUTION and user.organization_id:
            self.fields["case"].queryset = AuditCase.objects.filter(
                audited_organization_id=user.organization_id,
            ).exclude(
                status__in=[AuditCase.Status.DRAFT, AuditCase.Status.PENDING_PUBLICATION]
            ).select_related("audited_organization", "assigned_auditor")


class AuditInquiryReplyForm(forms.Form):
    body = forms.CharField(label="Mensaje", widget=forms.Textarea(attrs={"rows": 5}))
    attachment = forms.FileField(
        label="Archivo adjunto", required=False, validators=[validate_evidence_file],
        widget=forms.ClearableFileInput(attrs={"accept": EVIDENCE_ACCEPT}),
    )
    status_after = forms.ChoiceField(
        label="Estado después de enviar", required=False,
        choices=(
            (AuditInquiry.Status.ANSWERED, "Respondida"),
            (AuditInquiry.Status.WAITING_INSTITUTION, "Pendiente de información de la organización"),
            (AuditInquiry.Status.IN_PROGRESS, "Continuar en atención"),
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not user or user.role == User.Role.INSTITUTION:
            self.fields.pop("status_after")


class AuditInquiryManageForm(forms.Form):
    status = forms.ChoiceField(label="Nuevo estado", choices=AuditInquiry.Status.choices)
    assigned_auditor = forms.ModelChoiceField(
        label="Auditor responsable",
        queryset=User.objects.filter(role=User.Role.AUDITOR, is_active=True),
    )
    note = forms.CharField(
        label="Motivo del cambio", max_length=500, required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class AuditorCreateForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email", "job_title")

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Ya existe una cuenta con este correo electrónico.")
        return email

    def save(self, commit=True):
        auditor = super().save(commit=False)
        auditor.role = User.Role.AUDITOR
        auditor.organization = None
        auditor.is_staff = False
        auditor.is_superuser = False
        auditor.must_change_password = True
        if commit:
            auditor.save()
        return auditor


class AuditorEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "job_title")

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya existe una cuenta con este correo electrónico.")
        return email


class AuditCaseForm(forms.ModelForm):
    class Meta:
        model = AuditCase
        fields = (
            "reference",
            "title",
            "audited_organization",
            "report_date",
            "period_start",
            "period_end",
            "response_deadline",
            "assigned_auditor",
        )
        widgets = {
            "title": forms.Textarea(attrs={"rows": 2}),
            "audited_organization": OrganizationSearchSelect,
            "report_date": DateInput(),
            "period_start": DateInput(),
            "period_end": DateInput(),
            "response_deadline": DateInput(),
        }
        help_texts = {
            "reference": "Use la referencia oficial y única del expediente.",
            "response_deadline": "Fecha general para que las instituciones responsables respondan.",
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["audited_organization"].queryset = Organization.objects.filter(
            is_active=True
        ).only("code", "name").order_by("name")
        self.fields["assigned_auditor"].queryset = User.objects.filter(
            is_active=True,
            role=User.Role.AUDITOR,
        ).order_by("first_name", "last_name", "username")
        if user and user.role == User.Role.AUDITOR:
            assigned = user.assigned_organizations.filter(is_active=True)
            # Pocas organizaciones asignadas: lista completa en lugar del buscador del catálogo.
            self.fields["audited_organization"].widget = FastSelect()
            self.fields["audited_organization"].queryset = assigned.order_by("name")
            self.fields["audited_organization"].help_text = (
                "Solo se muestran las organizaciones que Dirección le ha asignado."
            )
            self.fields["assigned_auditor"].queryset = User.objects.filter(pk=user.pk)
            self.fields["assigned_auditor"].initial = user.pk
            self.fields["assigned_auditor"].disabled = True
            self.fields["assigned_auditor"].help_text = "El expediente quedará asignado a usted."

    def clean(self):
        cleaned = super().clean()
        period_start = cleaned.get("period_start")
        period_end = cleaned.get("period_end")
        report_date = cleaned.get("report_date")
        response_deadline = cleaned.get("response_deadline")
        if period_start and period_end and period_start > period_end:
            self.add_error("period_end", "El fin del período no puede ser anterior al inicio.")
        if report_date and response_deadline and response_deadline < report_date:
            self.add_error(
                "response_deadline",
                "La fecha límite de respuesta no puede ser anterior a la fecha del informe.",
            )
        return cleaned


class CaseReportDocumentForm(forms.ModelForm):
    class Meta:
        model = AuditDocument
        fields = ("reference", "title", "document_date", "file")
        widgets = {
            "document_date": DateInput(),
            "file": forms.ClearableFileInput(attrs={"accept": ".docx"}),
        }
        help_texts = {
            "file": "Cargue el informe elaborado en Word (.docx).",
            "reference": "Referencia que aparecerá en el historial del centro.",
        }

    def clean_file(self):
        document = self.cleaned_data.get("file")
        if document and Path(document.name).suffix.lower() != ".docx":
            raise forms.ValidationError("El informe debe cargarse en formato Word (.docx).")
        return document


class HistoricalDocumentForm(forms.ModelForm):
    class Meta:
        model = AuditDocument
        fields = (
            "organization",
            "reference",
            "title",
            "document_date",
            "file",
            "visibility",
        )
        widgets = {
            "organization": OrganizationSearchSelect,
            "document_date": DateInput(),
            "file": forms.ClearableFileInput(attrs={"accept": ".pdf,.docx"}),
        }
        help_texts = {
            "file": "Se admiten informes anteriores en PDF o Word (.docx).",
            "document_date": "Fecha original del informe; déjela vacía si no se conoce.",
            "visibility": "Defina quién puede consultar el informe y sus recomendaciones.",
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["organization"].queryset = Organization.objects.filter(
            is_active=True
        ).only("code", "name").order_by("name")
        if organization is not None:
            self.fields["organization"].queryset = Organization.objects.filter(pk=organization.pk)
            self.fields["organization"].initial = organization.pk
            self.fields["organization"].disabled = True

    def clean_file(self):
        document = self.cleaned_data.get("file")
        extension = Path(document.name).suffix.lower() if document else ""
        if extension not in {".pdf", ".docx"}:
            raise forms.ValidationError("El informe debe ser PDF o Word (.docx).")
        return document


class HistoricalAttachmentForm(forms.Form):
    document_type = forms.ChoiceField(label="Tipo de documento", choices=[
        (AuditDocument.DocumentType.NOTIFICATION, "Notificación u oficio"),
        (AuditDocument.DocumentType.HISTORICAL_RESPONSE, "Respuesta"),
        (AuditDocument.DocumentType.HISTORICAL_EVIDENCE, "Evidencia"),
        (AuditDocument.DocumentType.HISTORICAL_EXTENSION, "Prórroga"),
        (AuditDocument.DocumentType.HISTORICAL_CLOSURE, "Cierre"),
        (AuditDocument.DocumentType.OTHER, "Otro documento"),
    ], initial=AuditDocument.DocumentType.OTHER)
    title = forms.CharField(label="Descripción", max_length=300, required=False,
                           help_text="Si queda vacía, se utilizará el nombre del archivo.")
    reference = forms.CharField(label="Referencia del documento", max_length=80, required=False)
    document_date = forms.DateField(label="Fecha original", required=False,
                                   widget=DateInput())
    visibility = forms.ChoiceField(label="Visibilidad", choices=AuditDocument.Visibility.choices,
                                  initial=AuditDocument.Visibility.AUDIT_ONLY)
    file = forms.FileField(label="Archivo", validators=[validate_evidence_file],
        widget=forms.ClearableFileInput(attrs={"accept": EVIDENCE_ACCEPT}),
        help_text="PDF, Word, Excel o imagen. Un archivo por documento.")


class BaseHistoricalAttachmentFormSet(forms.BaseFormSet):
    def __init__(self, *args, require_one=False, **kwargs):
        self.require_one = require_one
        super().__init__(*args, **kwargs)

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        if self.require_one and not any(form.cleaned_data.get("file") for form in self.forms):
            raise forms.ValidationError("Agregue al menos un documento.")


HistoricalAttachmentFormSet = forms.formset_factory(
    HistoricalAttachmentForm, formset=BaseHistoricalAttachmentFormSet,
    extra=2, max_num=10, absolute_max=10, validate_max=True,
)


class HistoricalRecommendationForm(forms.ModelForm):
    class Meta:
        model = HistoricalRecommendation
        fields = (
            "number",
            "text",
            "responsible_organization",
            "responsible_description",
            "status",
            "comments",
            "original_deadline",
        )
        widgets = {
            "text": forms.Textarea(attrs={"rows": 6}),
            "responsible_organization": OrganizationSearchSelect,
            "comments": forms.Textarea(attrs={"rows": 4}),
            "original_deadline": DateInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible_organization"].queryset = Organization.objects.filter(
            is_active=True
        ).only("code", "name").order_by("name")


class HistoricalRecommendationImportForm(forms.Form):
    recommendations = forms.ModelMultipleChoiceField(
        label="Recomendaciones que se incorporarán",
        queryset=HistoricalRecommendation.objects.none(),
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        if queryset is not None:
            self.fields["recommendations"].queryset = queryset


class DeadlineExtensionForm(forms.ModelForm):
    class Meta:
        model = DeadlineExtension
        fields = ("business_days", "reason")
        widgets = {"reason": forms.Textarea(attrs={"rows": 4})}
        help_texts = {
            "business_days": "Se excluirán fines de semana y asuetos configurados.",
            "reason": "La prórroga y su fundamento quedarán en el expediente.",
        }


REQUIRED_TO_PUBLISH = "Obligatorio antes de solicitar la aprobación."

# Guía de redacción de los atributos del hallazgo y de la recomendación: una pregunta breve
# como ayuda y un ejemplo plegable que el auditor puede consultar sin salir del formulario.
FINDING_GUIDES = {
    "title": (
        "Resuma en una frase qué se incumple y dónde.",
        "Falta de conciliaciones bancarias mensuales de la cuenta de fondos de funcionamiento.",
    ),
    "risk_level": (
        "Valore el impacto del hallazgo si no se corrige.",
        None,
    ),
    "condition": (
        f"¿Qué se encontró? Hechos verificados, cifras, período y documentos revisados. {REQUIRED_TO_PUBLISH}",
        "Durante el período de enero a junio de 2026 el CDE no elaboró las conciliaciones "
        "bancarias de la cuenta de fondos de funcionamiento; en el expediente contable solo "
        "constan los estados de cuenta del banco.",
    ),
    "criteria": (
        f"¿Qué norma, disposición o procedimiento establece lo que debía hacerse? {REQUIRED_TO_PUBLISH}",
        "El instructivo para la administración de fondos transferidos a los centros educativos "
        "establece que el tesorero del CDE debe elaborar mensualmente la conciliación bancaria, "
        "firmada por el presidente y el tesorero.",
    ),
    "cause": (
        f"¿Por qué ocurrió? El origen del incumplimiento, no su consecuencia. {REQUIRED_TO_PUBLISH}",
        "El tesorero del CDE desconocía el procedimiento y no recibió inducción al asumir el cargo.",
    ),
    "effect": (
        f"¿Qué consecuencia o riesgo genera? Cuantifique cuando sea posible. {REQUIRED_TO_PUBLISH}",
        "No es posible verificar oportunamente la disponibilidad de fondos ni detectar cargos "
        "bancarios no autorizados por $1,250.00 registrados en el período.",
    ),
}

RECOMMENDATION_GUIDES = {
    "text": (
        "Indique quién debe hacer qué y cómo se corrige la causa. Empiece con un verbo en infinitivo o imperativo.",
        "Que el presidente del CDE gire instrucciones al tesorero para que elabore y firme "
        "mensualmente las conciliaciones bancarias, y que estas se archiven con los estados de cuenta.",
    ),
    "responsible_organization": (
        "Puede ser el centro auditado u otra dependencia responsable.",
        None,
    ),
    "deadline": (
        "Use un acceso rápido o elija la fecha en el calendario.",
        None,
    ),
    "evidence_requirements": (
        f"Liste los documentos que permitirán comprobar el cumplimiento, uno por línea. {REQUIRED_TO_PUBLISH}",
        "Conciliaciones bancarias de los últimos tres meses, firmadas.\n"
        "Acta del CDE donde se instruye al tesorero.",
    ),
}

DEADLINE_SHORTCUT_BUSINESS_DAYS = (10, 15, 30)

# Plazo sugerido según el riesgo del hallazgo; debe estar entre los accesos rápidos.
# Valores iniciales pendientes de confirmar con la Dirección de Auditoría Interna.
RISK_DEADLINE_BUSINESS_DAYS = {
    Finding.RiskLevel.CRITICAL: 10,
    Finding.RiskLevel.HIGH: 15,
    Finding.RiskLevel.MEDIUM: 30,
    Finding.RiskLevel.LOW: 30,
}

PLACEHOLDER_HINT = "Escriba entre [corchetes] los datos que el auditor debe completar en cada caso."


def apply_snippets(form, catalogs):
    for name, entries in catalogs.items():
        if name in form.fields:
            form.fields[name].snippets = build_snippets(entries)


def apply_guides(form, guides):
    for name, (help_text, example) in guides.items():
        field = form.fields.get(name)
        if field is None:
            continue
        field.help_text = help_text
        field.example = example


def category_queryset(current_id=None):
    """Áreas activas, más la que ya tiene el registro aunque se haya desactivado."""
    query = models.Q(is_active=True)
    if current_id:
        query |= models.Q(pk=current_id)
    return FindingCategory.objects.filter(query).order_by("name")


class FindingForm(forms.ModelForm):
    class Meta:
        model = Finding
        fields = ("number", "title", "risk_level", "category", "condition", "criteria", "cause", "effect")
        widgets = {
            "title": forms.Textarea(attrs={"rows": 2}),
            "category": FastSelect,
            "condition": forms.Textarea(attrs={"rows": 4}),
            "criteria": forms.Textarea(attrs={"rows": 3}),
            "cause": forms.Textarea(attrs={"rows": 3}),
            "effect": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_guides(self, FINDING_GUIDES)
        apply_snippets(self, FINDING_SNIPPETS)
        # El área se pide solo cuando Dirección ya definió el catálogo; mientras tanto no se muestra.
        if not FindingCategory.objects.filter(is_active=True).exists():
            del self.fields["category"]
            return
        category = self.fields["category"]
        category.queryset = category_queryset(self.instance.category_id)
        category.required = True
        category.help_text = "Clasifica el hallazgo para el análisis y la búsqueda en la biblioteca."


class FindingCategoryForm(forms.ModelForm):
    class Meta:
        model = FindingCategory
        fields = ("name", "description", "is_active")
        help_texts = {
            "description": "Opcional. Ayuda a los auditores a elegir el área correcta.",
            "is_active": "Las áreas inactivas no se ofrecen en hallazgos ni plantillas nuevas.",
        }


class FindingTemplateForm(forms.ModelForm):
    class Meta:
        model = FindingTemplate
        fields = ("category", "title", "risk_level", "condition", "criteria", "cause", "effect", "is_active")
        widgets = {
            "category": FastSelect,
            "title": forms.Textarea(attrs={"rows": 2}),
            "condition": forms.Textarea(attrs={"rows": 4}),
            "criteria": forms.Textarea(attrs={"rows": 3}),
            "cause": forms.Textarea(attrs={"rows": 3}),
            "effect": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_guides(self, FINDING_GUIDES)
        apply_snippets(self, FINDING_SNIPPETS)
        for name in ("condition", "criteria", "cause", "effect"):
            field = self.fields[name]
            field.help_text = f"{field.help_text.replace(REQUIRED_TO_PUBLISH, '').strip()} {PLACEHOLDER_HINT}"
        self.fields["category"].queryset = category_queryset(self.instance.category_id)
        self.fields["category"].required = True
        self.fields["is_active"].help_text = "Desmárquela para retirarla de la biblioteca sin perder el historial."


class RecommendationTemplateForm(forms.ModelForm):
    class Meta:
        model = RecommendationTemplate
        # El número se asigna según el orden de las tarjetas (ver library.save_recommendation_templates).
        fields = ("text", "evidence_requirements", "business_days")
        widgets = {
            "text": forms.Textarea(attrs={"rows": 4}),
            "evidence_requirements": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["evidence_requirements"].help_text = "Uno por línea."
        self.fields["evidence_requirements"].snippets = build_snippets(EVIDENCE_SNIPPETS, mode=LINE)
        self.fields["text"].snippets = build_snippets(RECOMMENDATION_SNIPPETS["text"])


class BaseRecommendationTemplateFormSet(forms.BaseInlineFormSet):
    def add_fields(self, form, index):
        super().add_fields(form, index)
        if "DELETE" in form.fields:
            form.fields["DELETE"].label = "Quitar esta recomendación"


RecommendationTemplateFormSet = forms.inlineformset_factory(
    FindingTemplate,
    RecommendationTemplate,
    form=RecommendationTemplateForm,
    formset=BaseRecommendationTemplateFormSet,
    extra=0,
    min_num=1,
    validate_min=True,
    can_delete=True,
)


class RecommendationForm(forms.ModelForm):
    class Meta:
        model = Recommendation
        fields = ("number", "text", "responsible_organization", "deadline", "evidence_requirements")
        widgets = {
            "text": forms.Textarea(attrs={"rows": 5}),
            "responsible_organization": OrganizationSearchSelect,
            "deadline": DateInput(),
            "evidence_requirements": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, deadline_shortcuts=None, learned_evidence=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible_organization"].queryset = Organization.objects.filter(
            is_active=True
        ).only("code", "name").order_by("name")
        apply_guides(self, RECOMMENDATION_GUIDES)
        self.fields["deadline"].shortcuts = deadline_shortcuts or []
        apply_snippets(self, RECOMMENDATION_SNIPPETS)
        self.fields["evidence_requirements"].snippets = build_snippets(EVIDENCE_SNIPPETS, mode=LINE)
        self.fields["evidence_requirements"].learned_snippets = list(learned_evidence or [])
        if not deadline_shortcuts:
            self.fields["deadline"].help_text = ""


class DecisionResolutionForm(forms.Form):
    class Action(models.TextChoices):
        APPROVE = "approve", "Aprobar"
        RETURN = "return", "Devolver"

    action = forms.ChoiceField(label="Decisión", choices=Action.choices)
    justification = forms.CharField(
        label="Justificación",
        min_length=10,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Explique el fundamento de la decisión. Quedará incorporado a la bitácora.",
    )


class CaseReservationForm(forms.Form):
    justification = forms.CharField(
        label="Justificación",
        min_length=10,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Queda en la bitácora. Por ejemplo: investigación especial o conflicto de interés.",
    )


class ClosureRequestForm(forms.Form):
    justification = forms.CharField(
        label="Fundamento de la solicitud de cierre",
        min_length=10,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Resuma por qué el expediente reúne las condiciones para su cierre.",
    )


class AuditorReassignmentForm(forms.Form):
    assigned_auditor = forms.ModelChoiceField(
        label="Nuevo auditor responsable",
        queryset=User.objects.none(),
    )
    justification = forms.CharField(
        label="Justificación de la reasignación",
        min_length=10,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="La reasignación y su fundamento quedarán registrados.",
    )

    def __init__(self, *args, current_auditor=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = User.objects.filter(is_active=True, role=User.Role.AUDITOR)
        if current_auditor:
            queryset = queryset.exclude(pk=current_auditor.pk)
        self.fields["assigned_auditor"].queryset = queryset.order_by(
            "first_name", "last_name", "username"
        )


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput)
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        clean_one = super().clean
        if isinstance(data, (list, tuple)):
            if not data and self.required:
                raise forms.ValidationError(
                    self.error_messages["required"],
                    code="required",
                )
            return [clean_one(item, initial) for item in data]
        if data:
            return [clean_one(data, initial)]
        if self.required:
            raise forms.ValidationError(
                self.error_messages["required"],
                code="required",
            )
        return []


class ResponseForm(forms.ModelForm):
    evidence_category = forms.ChoiceField(label="Tipo de documentación", choices=Evidence.Category.choices)
    evidence_description = forms.CharField(
        label="Descripción de la documentación",
        max_length=300,
        help_text="Indique la relación de los archivos adjuntos con las acciones reportadas.",
    )
    files = MultipleFileField(
        label="Documentos de respaldo",
        validators=[validate_evidence_file],
        widget=MultipleFileInput(attrs={"accept": EVIDENCE_ACCEPT}),
        help_text="Formatos admitidos: PDF, JPG, PNG, DOCX o XLSX. Se aplica el límite configurado por archivo.",
    )

    class Meta:
        model = Response
        fields = (
            "declared_status",
            "action_description",
            "action_date",
            "responsible_name",
            "responsible_job_title",
            "non_compliance_reason",
            "action_plan",
            "expected_completion_date",
            "accuracy_declaration",
        )
        widgets = {
            "action_description": forms.Textarea(attrs={"rows": 5}),
            "action_date": DateInput(),
            "non_compliance_reason": forms.Textarea(attrs={"rows": 3}),
            "action_plan": forms.Textarea(attrs={"rows": 3}),
            "expected_completion_date": DateInput(),
        }
        help_texts = {
            "accuracy_declaration": "Declaro que la información y los archivos presentados son correctos.",
        }

    covered_requirements = forms.MultipleChoiceField(
        label="Documentos que incluye",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Marque cada documento pedido que va en sus archivos. Auditoría lo verá al revisar.",
    )

    def __init__(self, *args, requirements=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.requirements = list(requirements or [])
        if self.requirements:
            self.fields["covered_requirements"].choices = [(item, item) for item in self.requirements]
        else:
            del self.fields["covered_requirements"]
        # Opciones visibles como tarjetas, sin la opción vacía «---------».
        status_field = self.fields["declared_status"]
        status_field.choices = Response.DeclaredStatus.choices
        status_field.widget = forms.RadioSelect(choices=Response.DeclaredStatus.choices)
        self.fields["files"].help_text = (
            f"PDF, foto (JPG o PNG), Word o Excel. Hasta {settings.FILE_MAX_UPLOAD_MB} MB cada uno."
        )

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get("declared_status")
        if status == Response.DeclaredStatus.COMPLETED and not cleaned.get("action_date"):
            self.add_error("action_date", "Indique la fecha en que se completó la acción.")
        if status == Response.DeclaredStatus.UNABLE:
            if not cleaned.get("non_compliance_reason"):
                self.add_error("non_compliance_reason", "Explique por qué no fue posible cumplir.")
            if not cleaned.get("action_plan"):
                self.add_error("action_plan", "Indique el plan de acción pendiente.")
            if not cleaned.get("expected_completion_date"):
                self.add_error("expected_completion_date", "Indique una fecha estimada de cumplimiento.")
        if not cleaned.get("accuracy_declaration"):
            self.add_error(
                "accuracy_declaration",
                "Debe aceptar la declaración de veracidad antes de enviar la respuesta.",
            )
        return cleaned

    def save(self, commit=True):
        response = super().save(commit=False)
        if self.requirements:
            # Se conserva el orden en que Auditoría pidió los documentos.
            marked = set(self.cleaned_data.get("covered_requirements") or [])
            response.covered_requirements = [item for item in self.requirements if item in marked]
        if commit:
            response.save()
        return response


class ReviewForm(forms.ModelForm):
    # Orden y palabras pensados para decidir: del mejor resultado al peor.
    OUTCOME_CHOICES = (
        (Review.Outcome.COMPLIED, "Cumplida"),
        (Review.Outcome.PARTIAL, "Parcialmente cumplida"),
        (Review.Outcome.CORRECTION_REQUIRED, "Pedir corrección"),
        (Review.Outcome.NOT_COMPLIED, "No cumplida"),
    )

    class Meta:
        model = Review
        fields = ("outcome", "comments")
        widgets = {"comments": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["outcome"].choices = self.OUTCOME_CHOICES
        self.fields["outcome"].widget = forms.RadioSelect(choices=self.OUTCOME_CHOICES)
