import unicodedata

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.accounts.models import User

from .models import Organization

MIN_QUERY_LENGTH = 2
MAX_RESULTS = 20
SEARCH_ROLES = {User.Role.TECHNICAL_ADMIN, User.Role.AUDIT_MANAGER, User.Role.AUDITOR}


def normalize(text):
    """Minúsculas y sin tildes, para que «jose» encuentre «José»."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


@login_required
@require_GET
def organization_search(request):
    """Busca organizaciones del catálogo por código o nombre para los formularios internos.

    Solo devuelve código y nombre, igual que las listas que reemplaza. El formulario
    vuelve a validar la elección contra su propio conjunto de organizaciones.
    """
    if not (request.user.is_superuser or request.user.role in SEARCH_ROLES):
        raise PermissionDenied("La búsqueda del catálogo es solo para personal interno.")
    terms = normalize(request.GET.get("q", "")).split()
    if len("".join(terms)) < MIN_QUERY_LENGTH:
        return JsonResponse({"results": []})
    organizations = Organization.objects.all()
    if request.GET.get("todas") != "1":
        organizations = organizations.filter(is_active=True)
    matches = []
    for pk, code, name in organizations.values_list("pk", "code", "name"):
        haystack = normalize(f"{code} {name}")
        if all(term in haystack for term in terms):
            # Primero el código exacto, luego los códigos que empiezan con lo escrito.
            normalized_code = normalize(code)
            rank = 0 if normalized_code == terms[0] else 1 if normalized_code.startswith(terms[0]) else 2
            matches.append((rank, name, code, pk))
    matches.sort(key=lambda match: (match[0], normalize(match[1])))
    return JsonResponse({
        "results": [
            {"id": pk, "text": f"{code} - {name}"} for _rank, name, code, pk in matches[:MAX_RESULTS]
        ],
        "more": len(matches) > MAX_RESULTS,
    })
