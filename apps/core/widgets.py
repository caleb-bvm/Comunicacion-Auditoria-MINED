from django import forms
from django.forms.utils import flatatt
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
