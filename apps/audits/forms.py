from pathlib import Path

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.db import models

from apps.accounts.models import User
from apps.institutions.models import Organization

from apps.core.validators import validate_evidence_file

from .models import (
    AuditCase,
    AuditDocument,
    AuditInquiry,
    DeadlineExtension,
    Evidence,
    Finding,
    HistoricalRecommendation,
    Recommendation,
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
            "report_date": forms.DateInput(attrs={"type": "date"}),
            "period_start": forms.DateInput(attrs={"type": "date"}),
            "period_end": forms.DateInput(attrs={"type": "date"}),
            "response_deadline": forms.DateInput(attrs={"type": "date"}),
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
        ).order_by("name")
        self.fields["assigned_auditor"].queryset = User.objects.filter(
            is_active=True,
            role=User.Role.AUDITOR,
        ).order_by("first_name", "last_name", "username")
        if user and user.role == User.Role.AUDITOR:
            assigned = user.assigned_organizations.filter(is_active=True)
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
            "document_date": forms.DateInput(attrs={"type": "date"}),
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
            "document_date": forms.DateInput(attrs={"type": "date"}),
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
        ).order_by("name")
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
                                   widget=forms.DateInput(attrs={"type": "date"}))
    visibility = forms.ChoiceField(label="Visibilidad", choices=AuditDocument.Visibility.choices,
                                  initial=AuditDocument.Visibility.AUDIT_ONLY)
    file = forms.FileField(label="Archivo", validators=[validate_evidence_file],
        widget=forms.ClearableFileInput(attrs={"accept": ".pdf,.docx,.xlsx,.jpg,.jpeg,.png"}),
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
            "comments": forms.Textarea(attrs={"rows": 4}),
            "original_deadline": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible_organization"].queryset = Organization.objects.filter(
            is_active=True
        ).order_by("name")


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


class FindingForm(forms.ModelForm):
    class Meta:
        model = Finding
        fields = ("number", "title", "risk_level", "condition", "criteria", "cause", "effect")
        widgets = {
            "title": forms.Textarea(attrs={"rows": 2}),
            "condition": forms.Textarea(attrs={"rows": 4}),
            "criteria": forms.Textarea(attrs={"rows": 3}),
            "cause": forms.Textarea(attrs={"rows": 3}),
            "effect": forms.Textarea(attrs={"rows": 3}),
        }


class RecommendationForm(forms.ModelForm):
    class Meta:
        model = Recommendation
        fields = ("number", "text", "responsible_organization", "deadline", "evidence_requirements")
        widgets = {
            "text": forms.Textarea(attrs={"rows": 5}),
            "deadline": forms.DateInput(attrs={"type": "date"}),
            "evidence_requirements": forms.Textarea(attrs={"rows": 4}),
        }
        help_texts = {
            "responsible_organization": "Puede ser el centro auditado u otra dependencia responsable.",
            "evidence_requirements": "Detalle los documentos que permitirán comprobar el cumplimiento.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible_organization"].queryset = Organization.objects.filter(
            is_active=True
        ).order_by("name")


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
            "action_date": forms.DateInput(attrs={"type": "date"}),
            "non_compliance_reason": forms.Textarea(attrs={"rows": 3}),
            "action_plan": forms.Textarea(attrs={"rows": 3}),
            "expected_completion_date": forms.DateInput(attrs={"type": "date"}),
        }
        help_texts = {
            "accuracy_declaration": "Declaro que la información y los archivos presentados son correctos.",
        }

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


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ("outcome", "comments")
        widgets = {"comments": forms.Textarea(attrs={"rows": 6})}
