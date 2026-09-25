from django import forms

from apps.institutions.models import Organization

from .models import TechnicalSupportRequest


class TechnicalSupportRequestForm(forms.ModelForm):
    class Meta:
        model = TechnicalSupportRequest
        fields = ("category", "subject", "organization", "description")
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["organization"].queryset = Organization.objects.order_by("name")
        self.fields["organization"].required = False


class InstitutionTechnicalSupportRequestForm(forms.ModelForm):
    class Meta:
        model = TechnicalSupportRequest
        fields = ("category", "subject", "description")
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        excluded = {
            TechnicalSupportRequest.Category.PASSWORD_RESET,
            TechnicalSupportRequest.Category.ACCOUNT_REACTIVATION,
        }
        self.fields["category"].choices = [
            choice for choice in TechnicalSupportRequest.Category.choices
            if choice[0] not in excluded
        ]


class PublicPasswordSupportRequestForm(forms.Form):
    category = forms.ChoiceField(
        label="¿Qué problema necesita resolver?",
        choices=(
            (TechnicalSupportRequest.Category.ACCOUNT_REACTIVATION, "Mi cuenta está bloqueada o inactiva"),
            (TechnicalSupportRequest.Category.ACCESS_DATA, "Mi usuario o datos de acceso son incorrectos"),
            (TechnicalSupportRequest.Category.TECHNICAL_ERROR, "El sistema muestra un error al ingresar"),
            (TechnicalSupportRequest.Category.OTHER, "Otro problema de acceso"),
        ),
    )
    full_name = forms.CharField(label="Nombre completo", max_length=180)
    identifier = forms.CharField(
        label="Usuario o correo institucional", max_length=254,
        help_text="Para centros educativos puede ingresar el código del centro.",
    )
    contact_email = forms.EmailField(
        label="Correo de contacto",
        help_text="Se usará para seguimiento; el enlace solo se enviará al correo registrado.",
    )
    description = forms.CharField(
        label="Detalle del problema", min_length=10, max_length=1500,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("No fue posible procesar la solicitud.")
        return ""


class PasswordResetRequestForm(forms.Form):
    identifier = forms.CharField(
        label="Usuario, código del centro o correo institucional",
        max_length=254,
        help_text="El enlace se enviará únicamente al correo registrado en la cuenta.",
    )
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("No fue posible procesar la solicitud.")
        return ""


class TechnicalSupportResolutionForm(forms.Form):
    status = forms.ChoiceField(
        label="Nuevo estado",
        choices=(
            (TechnicalSupportRequest.Status.IN_PROGRESS, "En atención"),
            (TechnicalSupportRequest.Status.RESOLVED, "Resuelta"),
            (TechnicalSupportRequest.Status.CLOSED, "Cerrada"),
        ),
    )
    resolution = forms.CharField(label="Respuesta o resolución", widget=forms.Textarea(attrs={"rows": 4}))
