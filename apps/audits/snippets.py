"""Frases frecuentes que el personal auditor inserta con un toque en los formularios.

Cada catálogo es una lista de (etiqueta corta del chip, texto que se inserta). El
contenido es editable sin tocar vistas ni plantillas; debe validarse con la Dirección
de Auditoría Interna antes de ampliarlo.

Modos de inserción:
- "insert": agrega la frase donde está el cursor (o al final) dentro del texto.
- "line": agrega o quita la frase como una línea propia (listas de evidencias).
"""

from collections import Counter

INSERT = "insert"
LINE = "line"

FINDING_SNIPPETS = {
    "criteria": [
        ("Ley General de Educación", "la Ley General de Educación"),
        ("Ley de la Carrera Docente", "la Ley de la Carrera Docente"),
        ("Ley de Compras Públicas", "la Ley de Compras Públicas"),
        ("Ley de la Corte de Cuentas", "la Ley de la Corte de Cuentas de la República"),
        (
            "Normas de control interno",
            "las Normas Técnicas de Control Interno Específicas del Ministerio de Educación",
        ),
    ],
    "cause": [
        ("Desconocimiento de la norma", "Desconocimiento de la normativa aplicable por parte del personal responsable."),
        ("Falta de capacitación", "Falta de capacitación del personal responsable."),
        ("Falta de supervisión", "Falta de supervisión por parte de la dirección del centro educativo."),
        ("Sin controles internos", "Ausencia de controles internos que aseguren el cumplimiento del procedimiento."),
        ("Sin responsable asignado", "No se designó formalmente a un responsable de la actividad."),
    ],
    "effect": [
        ("Riesgo en uso de fondos", "Riesgo de uso inadecuado de los fondos asignados al centro educativo."),
        ("Falta de transparencia", "Falta de transparencia en la administración de los recursos."),
        ("Riesgo de pérdida de bienes", "Riesgo de pérdida o extravío de bienes institucionales."),
        ("Información no confiable", "La información financiera y administrativa no es confiable ni oportuna."),
        ("Incumplimiento normativo", "Incumplimiento de las disposiciones legales y técnicas aplicables."),
    ],
}

RECOMMENDATION_SNIPPETS = {
    "text": [
        ("Que el director…", "Que el director del centro educativo "),
        ("Que el CDE…", "Que el Consejo Directivo Escolar "),
        ("Que el tesorero…", "Que el tesorero del Consejo Directivo Escolar "),
        ("…gire instrucciones", "gire instrucciones por escrito para que "),
        ("…y documente", "y documente las acciones realizadas."),
    ],
}

EVIDENCE_SNIPPETS = [
    ("Acta del CDE", "Acta del CDE donde conste el acuerdo o la instrucción."),
    ("Conciliaciones bancarias", "Conciliaciones bancarias firmadas."),
    ("Estados de cuenta", "Estados de cuenta bancarios del período."),
    ("Facturas o recibos", "Facturas o recibos que respalden los gastos."),
    ("Registros contables", "Registros contables actualizados."),
    ("Inventario actualizado", "Inventario de bienes actualizado y firmado."),
    ("Contratos", "Contratos firmados."),
    ("Fotografías", "Fotografías de las acciones realizadas."),
]

# Cantidad máxima de líneas propias del auditor que se ofrecen además del catálogo.
MAX_LEARNED_EVIDENCE = 6
LEARNED_LABEL_LENGTH = 32


def build_snippets(entries, mode=INSERT):
    return [{"label": label, "text": text, "mode": mode} for label, text in entries]


def learned_evidence_snippets(recommendations, limit=MAX_LEARNED_EVIDENCE):
    """Líneas de evidencia que el auditor ha usado más, sin repetir el catálogo base.

    `recommendations` es un queryset ya limitado al alcance del usuario."""
    known = {text.casefold() for _, text in EVIDENCE_SNIPPETS}
    counter = Counter()
    original = {}
    for block in recommendations.values_list("evidence_requirements", flat=True)[:500]:
        for line in (block or "").splitlines():
            line = line.strip().lstrip("-•*").strip()
            key = line.casefold()
            if len(line) < 4 or key in known:
                continue
            counter[key] += 1
            original.setdefault(key, line)
    learned = []
    for key, count in counter.most_common():
        if count < 2 or len(learned) >= limit:
            break
        text = original[key]
        label = text if len(text) <= LEARNED_LABEL_LENGTH else f"{text[:LEARNED_LABEL_LENGTH - 1].rstrip()}…"
        learned.append({"label": label, "text": text, "mode": LINE, "learned": True})
    return learned
