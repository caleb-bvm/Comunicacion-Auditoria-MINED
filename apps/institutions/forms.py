from django import forms

from apps.core.validators import EVIDENCE_ACCEPT
from apps.core.widgets import DateInput

from .models import SchoolBoardMember, SchoolBoardPeriod


class SchoolBoardPeriodForm(forms.ModelForm):
    class Meta:
        model = SchoolBoardPeriod
        fields = (
            "start_date",
            "end_date",
            "school_year_start",
            "school_year_end",
            "supporting_document",
            "notes",
        )
        widgets = {
            "start_date": DateInput(),
            "end_date": DateInput(),
            "supporting_document": forms.ClearableFileInput(attrs={"accept": EVIDENCE_ACCEPT}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }
        help_texts = {
            "supporting_document": (
                "Adjunte el acta o documento que acredita la conformación del CDE."
            ),
            "notes": "Opcional. Registre únicamente información relevante para este período.",
        }


class SchoolBoardPeriodCorrectionForm(forms.ModelForm):
    class Meta:
        model = SchoolBoardPeriod
        fields = (
            "start_date",
            "end_date",
            "school_year_start",
            "school_year_end",
            "notes",
        )
        widgets = {
            "start_date": DateInput(),
            "end_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }
        help_texts = {
            "notes": "Opcional. La corrección quedará registrada en la bitácora.",
        }


class SchoolBoardMemberForm(forms.ModelForm):
    class Meta:
        model = SchoolBoardMember
        fields = (
            "full_name",
            "identity_document",
            "position",
            "sector",
            "is_legal_representative",
            "joined_on",
        )
        widgets = {
            "identity_document": forms.TextInput(
                attrs={
                    "placeholder": "00000000-0",
                    "maxlength": "10",
                    "pattern": r"[0-9]{8}-[0-9]",
                    "title": "Número de DUI",
                    "autocomplete": "off",
                }
            ),
            "joined_on": DateInput(),
        }
        help_texts = {
            "identity_document": "Formato: 00000000-0.",
            "is_legal_representative": (
                "Marque esta opción si la persona representa legalmente al centro durante el período."
            ),
        }


class SchoolBoardMemberDepartureForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["left_on"].required = True
        self.fields["exit_reason"].required = True

    class Meta:
        model = SchoolBoardMember
        fields = ("left_on", "exit_reason", "change_document")
        widgets = {
            "left_on": DateInput(),
            "exit_reason": forms.Textarea(attrs={"rows": 4}),
            "change_document": forms.ClearableFileInput(attrs={"accept": EVIDENCE_ACCEPT}),
        }
        help_texts = {
            "change_document": (
                "Opcional. Adjunte el documento que respalda la salida o sustitución."
            ),
        }

    def clean_left_on(self):
        left_on = self.cleaned_data["left_on"]
        if left_on and self.instance.joined_on and left_on < self.instance.joined_on:
            raise forms.ValidationError(
                "La fecha de salida no puede ser anterior a la incorporación."
            )
        return left_on
