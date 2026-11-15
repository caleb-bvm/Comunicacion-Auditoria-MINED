from django import forms
from django.core.exceptions import ValidationError
from django.forms.utils import flatatt
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe


class FastSelect(forms.Select):
    """Select que arma sus opciones en Python en lugar de una plantilla por opción.

    El catálogo tiene más de 6000 organizaciones; con el ``Select`` estándar cada
    formulario tardaba cerca de un segundo solo en dibujar la lista. El HTML
    resultante es el mismo que produce la plantilla de Django.
    """

    def render(self, name, value, attrs=None, renderer=None):
        widget = self.get_context(name, value, attrs)["widget"]
        parts = [format_html('<select name="{}"{}>', widget["name"], flatatt(widget["attrs"]))]
        for group_name, options, _index in widget["optgroups"]:
            if group_name:
                parts.append(format_html('<optgroup label="{}">', group_name))
            for option in options:
                parts.append(
                    format_html(
                        '<option value="{}"{}>{}</option>',
                        option["value"],
                        flatatt(option["attrs"]),
                        option["label"],
                    )
                )
            if group_name:
                parts.append("</optgroup>")
        parts.append("</select>")
        return mark_safe("".join(parts))


class OrganizationSearchSelect(FastSelect):
    """Campo de búsqueda para elegir una organización del catálogo.

    En lugar de enviar las 6000 opciones, el ``<select>`` lleva solo la opción
    vacía y la elegida; ``app.js`` lo convierte en un buscador que consulta
    ``organization_search``. El formulario sigue validando contra su queryset.
    ``include_inactive`` amplía la búsqueda a organizaciones inactivas.
    """

    def __init__(self, attrs=None, include_inactive=False):
        super().__init__(attrs)
        self.include_inactive = include_inactive

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        url = reverse("organization_search")
        context["widget"]["attrs"]["data-org-search"] = (
            f"{url}?todas=1" if self.include_inactive else url
        )
        return context

    def optgroups(self, name, value, attrs=None):
        field = getattr(self.choices, "field", None)
        if field is None:
            return super().optgroups(name, value, attrs)
        choices = []
        if field.empty_label is not None:
            choices.append(("", field.empty_label))
        selected = [item for item in value if item not in ("", None)]
        if selected:
            try:
                instances = list(field.queryset.filter(pk__in=selected))
            except (ValueError, ValidationError):
                instances = []
            choices.extend((str(instance.pk), field.label_from_instance(instance)) for instance in instances)
        return [
            (None, [self.create_option(name, option_value, label, option_value in selected, index, attrs=attrs)], index)
            for index, (option_value, label) in enumerate(choices)
        ]
