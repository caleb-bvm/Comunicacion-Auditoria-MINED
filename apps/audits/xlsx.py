from datetime import date, datetime
from io import BytesIO
from math import ceil

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo


NAVY = "0E3A7D"  # tokens.css --ui-primary-hover
BLUE = "1A4D9C"  # --ui-primary
LIGHT_BLUE = "D7E3FF"  # --ui-primary-container
LIGHT_GRAY = "F4F7F9"
MID_GRAY = "5F6B76"
LINE = "D7E0E8"
WHITE = "FFFFFF"
RED = "B3261E"  # --ui-danger: mismo rojo de «problema» que la web
LIGHT_RED = "FFDAD6"  # --ui-danger-container

SECTION_BORDER = Border(bottom=Side(style="medium", color=BLUE))

def _display_user(user):
    if not user:
        return ""
    return user.get_full_name() or user.username


def _safe_text(value, max_length=32767):
    """Keep database text as text in Excel and avoid formula injection."""
    if value is None:
        return ""
    text = ILLEGAL_CHARACTERS_RE.sub("", str(value))
    if text.lstrip().startswith(("=", "+", "-", "@")):
        text = f"'{text}"
    if len(text) > max_length:
        text = f"{text[: max_length - 24]} … [texto truncado]"
    return text


def _excel_datetime(value):
    if not value:
        return None
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.replace(tzinfo=None)


def _write_section_title(worksheet, row, title, end_column):
    worksheet.merge_cells(
        start_row=row,
        start_column=1,
        end_row=row,
        end_column=end_column,
    )
    cell = worksheet.cell(row=row, column=1, value=title)
    cell.font = Font(name="Aptos Display", size=14, bold=True, color=NAVY)
    cell.border = SECTION_BORDER
    cell.alignment = Alignment(vertical="center")
    worksheet.row_dimensions[row].height = 24


def _write_section_title_range(worksheet, row, start_column, end_column, title):
    worksheet.merge_cells(
        start_row=row,
        start_column=start_column,
        end_row=row,
        end_column=end_column,
    )
    cell = worksheet.cell(row=row, column=start_column, value=title)
    cell.font = Font(name="Aptos Display", size=14, bold=True, color=NAVY)
    cell.border = SECTION_BORDER
    cell.alignment = Alignment(vertical="center")
    worksheet.row_dimensions[row].height = 24


def _style_table_header(row_cells):
    for cell in row_cells:
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.font = Font(name="Aptos", size=10, bold=True, color=WHITE)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(bottom=Side(style="medium", color=BLUE))


def _add_table(worksheet, reference, name):
    table = Table(displayName=name, ref=reference)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    worksheet.add_table(table)


def _apply_sheet_setup(worksheet, landscape=True):
    worksheet.sheet_view.showGridLines = False
    worksheet.freeze_panes = "A5"
    worksheet.auto_filter.ref = worksheet.dimensions
    worksheet.sheet_properties.pageSetUpPr.fitToPage = True
    worksheet.page_setup.fitToWidth = 1
    worksheet.page_setup.fitToHeight = 0
    worksheet.page_setup.orientation = "landscape" if landscape else "portrait"
    worksheet.page_setup.paperSize = worksheet.PAPERSIZE_LETTER
    worksheet.print_title_rows = "1:4"
    worksheet.sheet_properties.outlinePr.summaryBelow = True
    worksheet.oddFooter.center.text = "Página &P de &N"
    worksheet.oddFooter.right.text = "Dirección de Auditoría Interna"
    worksheet.oddFooter.center.size = 8
    worksheet.oddFooter.right.size = 8


def _create_data_sheet(
    workbook,
    *,
    title,
    description,
    headers,
    rows,
    table_name,
    widths=None,
    date_columns=(),
    datetime_columns=(),
    percentage_columns=(),
    integer_columns=(),
    wrap_columns=(),
    landscape=True,
):
    worksheet = workbook.create_sheet(title=title)
    end_column = len(headers)
    worksheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=end_column)
    title_cell = worksheet.cell(row=1, column=1, value=title)
    title_cell.fill = PatternFill("solid", fgColor=NAVY)
    title_cell.font = Font(name="Aptos Display", size=18, bold=True, color=WHITE)
    title_cell.alignment = Alignment(vertical="center")
    worksheet.row_dimensions[1].height = 34

    worksheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=end_column)
    description_cell = worksheet.cell(row=2, column=1, value=description)
    description_cell.fill = PatternFill("solid", fgColor=LIGHT_BLUE)
    description_cell.font = Font(name="Aptos", size=9, color=NAVY, italic=True)
    description_cell.alignment = Alignment(vertical="center", wrap_text=True)
    worksheet.row_dimensions[2].height = 30

    header_row = 4
    for column, header in enumerate(headers, start=1):
        worksheet.cell(row=header_row, column=column, value=header)
    _style_table_header(worksheet[header_row])
    worksheet.row_dimensions[header_row].height = 34

    for row_index, values in enumerate(rows, start=header_row + 1):
        for column_index, value in enumerate(values, start=1):
            if isinstance(value, str):
                value = _safe_text(value)
            cell = worksheet.cell(row=row_index, column=column_index, value=value)
            cell.font = Font(name="Aptos", size=9, color="17212B")
            cell.alignment = Alignment(
                vertical="top",
                wrap_text=column_index in wrap_columns,
            )
            if column_index in date_columns and value:
                cell.number_format = "dd/mm/yyyy"
            elif column_index in datetime_columns and value:
                cell.number_format = "dd/mm/yyyy hh:mm"
            elif column_index in percentage_columns and value is not None:
                cell.number_format = "0%"
                cell.alignment = Alignment(horizontal="right", vertical="top")
            elif column_index in integer_columns and value is not None:
                cell.number_format = "#,##0"
                cell.alignment = Alignment(horizontal="right", vertical="top")

    last_row = header_row + len(rows)
    if rows:
        reference = f"A{header_row}:{get_column_letter(end_column)}{last_row}"
        _add_table(worksheet, reference, table_name)
    else:
        worksheet.merge_cells(
            start_row=header_row + 1,
            start_column=1,
            end_row=header_row + 1,
            end_column=end_column,
        )
        empty_cell = worksheet.cell(row=header_row + 1, column=1, value="Sin registros para los filtros seleccionados.")
        empty_cell.fill = PatternFill("solid", fgColor=LIGHT_GRAY)
        empty_cell.font = Font(name="Aptos", size=10, italic=True, color=MID_GRAY)
        empty_cell.alignment = Alignment(horizontal="center", vertical="center")
        worksheet.row_dimensions[header_row + 1].height = 28

    widths = widths or {}
    for column_index, header in enumerate(headers, start=1):
        configured = widths.get(column_index)
        if configured:
            width = configured
        else:
            lengths = [len(str(header))]
            for values in rows[:100]:
                value = values[column_index - 1]
                if value is not None:
                    lengths.append(len(str(value).split("\n", 1)[0]))
            width = min(max(max(lengths) + 2, 11), 35)
        worksheet.column_dimensions[get_column_letter(column_index)].width = width

    _apply_sheet_setup(worksheet, landscape=landscape)
    worksheet.auto_filter.ref = (
        f"A{header_row}:{get_column_letter(end_column)}{max(last_row, header_row)}"
    )
    worksheet.print_area = f"A1:{get_column_letter(end_column)}{max(last_row, header_row + 1)}"
    return worksheet


def _auditor_rows(auditor_statistics):
    output = []
    for row in auditor_statistics:
        terminal = row.get("terminal_count", 0)
        output.append(
            [
                _display_user(row["auditor"]),
                row["auditor"].username,
                row["auditor"].job_title,
                "Sí" if row["auditor"].is_active else "No",
                row["cases_count"],
                row["open_cases_count"],
                row.get("in_management_count", row["open_cases_count"]),
                row["recommendation_count"],
                row.get("complied_count", 0),
                row.get("partial_count", 0),
                row.get("not_complied_count", 0),
                row["pending_reviews_count"],
                row["overdue_count"],
                row.get("complied_count", 0) / terminal if terminal else None,
            ]
        )
    return output


def _organization_rows(organization_statistics):
    output = []
    for row in organization_statistics:
        terminal = row.get("terminal_count", 0)
        output.append(
            [
                row["code"],
                row["name"],
                row.get("kind", ""),
                row.get("department", ""),
                row.get("municipality", ""),
                row["cases_count"],
                row["open_cases_count"],
                row.get("in_management_count", row["open_cases_count"]),
                row["recommendation_count"],
                row.get("complied_count", 0),
                row.get("partial_count", 0),
                row.get("not_complied_count", 0),
                row["overdue_count"],
                row["critical_count"],
                row.get("complied_count", 0) / terminal if terminal else None,
            ]
        )
    return output


def _territorial_filter_rows(analysis):
    mode_label = (
        "Situación vigente (historial consolidado)"
        if analysis["selected_mode"] == "current"
        else "Actividad del período"
    )
    period_label = (
        "Todo el historial consolidado"
        if analysis["selected_mode"] == "current"
        else analysis["selected_period_label"]
    )
    quick_filter_label = next(
        (
            item["label"]
            for item in analysis["quick_filters"]
            if item["value"] == analysis["selected_quick_filter"]
        ),
        "Ninguno",
    )
    filter_labels = {
        "attention": {
            "immediate": "Atención inmediata",
            "high": "Prioridad alta",
            "followup": "Seguimiento",
            "stable": "Sin alertas actuales",
        },
        "coverage": {"audited": "Auditados", "not_audited": "Nunca auditados"},
        "risk": {"critical": "Riesgo crítico", "high": "Riesgo alto o crítico"},
        "cde": {"current": "CDE vigente", "pending": "Sin CDE vigente"},
        "access": {"active": "Acceso activo", "pending": "Sin acceso activo"},
        "compliance": {
            "not_available": "Sin resultados definitivos",
            "low": "Menos de 50%",
            "medium": "50% a 79%",
            "high": "80% a 99%",
            "complete": "100%",
        },
    }

    def selected_label(group, value):
        return filter_labels[group].get(value, "Todos")

    return [
        ("Perspectiva", mode_label),
        ("Período", period_label),
        ("Fecha inicial", analysis["start_date"] if analysis["selected_mode"] == "activity" else None),
        ("Fecha final", analysis["end_date"] if analysis["selected_mode"] == "activity" else None),
        ("Departamento", analysis["selected_department"] or "Todos"),
        ("Distrito", analysis["selected_district"] or "Todos"),
        ("Agrupación", analysis["selected_group_label"]),
        ("Filtro rápido", quick_filter_label),
        ("Nivel de atención", selected_label("attention", analysis["selected_attention"])),
        ("Cobertura", selected_label("coverage", analysis["selected_coverage"])),
        ("Riesgo", selected_label("risk", analysis["selected_risk"])),
        ("CDE", selected_label("cde", analysis["selected_cde"])),
        ("Acceso", selected_label("access", analysis["selected_access"])),
        ("Cumplimiento", selected_label("compliance", analysis["selected_compliance"])),
    ]


def _create_territorial_summary_sheet(
    workbook,
    *,
    report_id,
    analysis,
    generated_by,
    generated_at,
):
    worksheet = workbook.active
    worksheet.title = "Resumen"
    worksheet.sheet_view.showGridLines = False

    worksheet.merge_cells("A1:H1")
    worksheet["A1"] = "Análisis territorial de centros educativos"
    worksheet["A1"].fill = PatternFill("solid", fgColor=NAVY)
    worksheet["A1"].font = Font(name="Aptos Display", size=18, bold=True, color=WHITE)
    worksheet["A1"].alignment = Alignment(vertical="center")
    worksheet.row_dimensions[1].height = 34

    worksheet.merge_cells("A2:H2")
    worksheet["A2"] = (
        "La situación vigente usa el historial consolidado; la actividad respeta la fecha propia "
        "de cada evento dentro del período seleccionado."
    )
    worksheet["A2"].fill = PatternFill("solid", fgColor=LIGHT_BLUE)
    worksheet["A2"].font = Font(name="Aptos", size=9, color=NAVY, italic=True)
    worksheet["A2"].alignment = Alignment(vertical="center", wrap_text=True)
    worksheet.row_dimensions[2].height = 32

    _write_section_title(worksheet, 4, "Identificación del informe", 3)
    identification = (
        ("Folio", report_id),
        ("Generado", _excel_datetime(generated_at)),
        ("Generado por", _display_user(generated_by)),
    )
    for row, (label, value) in enumerate(identification, start=5):
        worksheet.cell(row=row, column=1, value=label).font = Font(name="Aptos", size=10, bold=True, color=NAVY)
        worksheet.merge_cells(start_row=row, start_column=2, end_row=row, end_column=3)
        cell = worksheet.cell(row=row, column=2, value=_safe_text(value) if isinstance(value, str) else value)
        cell.font = Font(name="Aptos", size=10, color="17212B")
        if isinstance(value, datetime):
            cell.number_format = "dd/mm/yyyy hh:mm"

    _write_section_title_range(worksheet, 4, 4, 8, "Situación vigente")
    indicators = (
        ("Centros en el alcance", analysis["center_count"], "count"),
        ("Centros auditados", analysis["audited_center_count"], "count"),
        ("Cobertura", analysis["coverage_rate"] / 100, "percentage"),
        ("Atención inmediata", analysis["immediate_center_count"], "count"),
        ("Centros con vencimientos", analysis["overdue_center_count"], "count"),
        ("Obligaciones vencidas", analysis["overdue_obligations"], "count"),
        ("Centros con riesgo crítico", analysis["critical_center_count"], "count"),
        (
            "Cumplimiento territorial",
            (
                analysis["territorial_compliance_rate"] / 100
                if analysis["territorial_compliance_rate"] is not None
                else "N/D"
            ),
            "percentage",
        ),
    )
    for row, (label, value, value_type) in enumerate(indicators, start=5):
        worksheet.cell(row=row, column=4, value=label).font = Font(name="Aptos", size=10, bold=True, color=NAVY)
        worksheet.merge_cells(start_row=row, start_column=5, end_row=row, end_column=6)
        value_cell = worksheet.cell(row=row, column=5, value=value)
        value_cell.font = Font(name="Aptos", size=11, bold=True, color="17212B")
        value_cell.alignment = Alignment(horizontal="right")
        if value_type == "percentage" and isinstance(value, (int, float)):
            value_cell.number_format = "0%"

    _write_section_title(worksheet, 10, "Filtros aplicados", 3)
    for row, (label, value) in enumerate(_territorial_filter_rows(analysis), start=11):
        worksheet.cell(row=row, column=1, value=label).font = Font(name="Aptos", size=9, bold=True, color=NAVY)
        worksheet.merge_cells(start_row=row, start_column=2, end_row=row, end_column=3)
        cell = worksheet.cell(row=row, column=2, value=_safe_text(value) if isinstance(value, str) else value)
        cell.font = Font(name="Aptos", size=9, color="17212B")
        if isinstance(value, date):
            cell.number_format = "dd/mm/yyyy"

    _write_section_title_range(worksheet, 15, 4, 8, "Actividad del período")
    activity = (
        ("Expedientes registrados", analysis["activity_case_count"]),
        ("Informes emitidos", analysis["activity_report_count"]),
        ("Hallazgos registrados", analysis["activity_finding_count"]),
        ("Hallazgos críticos", analysis["activity_critical_count"]),
        ("Recomendaciones registradas", analysis["activity_recommendation_count"]),
        ("Respuestas presentadas", analysis["activity_response_count"]),
        ("Dictámenes emitidos", analysis["activity_review_count"]),
        ("Prórrogas concedidas", analysis["activity_extension_count"]),
        ("Incumplimientos automáticos", analysis["activity_automatic_no_response_count"]),
    )
    for row, (label, value) in enumerate(activity, start=16):
        worksheet.cell(row=row, column=4, value=label).font = Font(name="Aptos", size=9, bold=True, color=NAVY)
        worksheet.cell(row=row, column=5, value=value).font = Font(name="Aptos", size=10, bold=True, color="17212B")
        worksheet.cell(row=row, column=5).number_format = "#,##0"

    for column, width in {"A": 26, "B": 25, "C": 4, "D": 30, "E": 16, "F": 4, "G": 4, "H": 4}.items():
        worksheet.column_dimensions[column].width = width
    worksheet.freeze_panes = "A4"
    worksheet.page_setup.orientation = "landscape"
    worksheet.page_setup.fitToWidth = 1
    worksheet.page_setup.fitToHeight = 1
    worksheet.sheet_properties.pageSetUpPr.fitToPage = True
    worksheet.print_area = "A1:H25"
    return worksheet


def _territorial_center_rows(centers):
    rows = []
    for center in centers:
        reasons = "; ".join(reason["label"] for reason in center.attention_reasons)
        rows.append(
            [
                center.code,
                center.name,
                center.department,
                getattr(center, "district", ""),
                center.municipality,
                center.attention_label,
                reasons,
                center.case_count,
                center.active_case_count,
                center.finding_count,
                center.critical_active_count,
                center.high_active_count,
                center.obligation_count,
                center.overdue_count,
                center.due_soon_count,
                center.pending_count,
                center.submitted_count,
                center.under_review_count,
                center.correction_count,
                center.complied_count,
                center.partial_count,
                center.not_complied_count,
                center.compliance_rate / 100 if center.compliance_rate is not None else None,
                center.cde_state_label,
                center.access_label,
                center.latest_report_date,
                _excel_datetime(center.latest_activity_at),
            ]
        )
    return rows


TERRITORIAL_EXPORT_DEPTHS = {
    "light": "Análisis ligero",
    "deep": "Análisis profundo",
}


def _create_light_center_sheet(workbook, analysis):
    rows = [
        [
            center.code, center.name, center.department,
            getattr(center, "district", ""), center.attention_label,
            center.obligation_count, center.overdue_count, center.due_soon_count,
            center.submitted_count + center.under_review_count,
            center.correction_count,
            center.compliance_rate / 100 if center.compliance_rate is not None else "N/D",
            "; ".join(reason["label"] for reason in center.attention_reasons) or "Sin alertas actuales",
        ]
        for center in analysis["centers"]
    ]
    sheet = _create_data_sheet(
        workbook,
        title="Centros educativos",
        description=(
            "Todos los centros de los filtros seleccionados. Cumplimiento: cumplidas / resultados "
            "definitivos. N/D: sin resultados definitivos. Plazos según la última prórroga."
        ),
        headers=(
            "Código", "Centro educativo", "Departamento", "Distrito", "Nivel de atención",
            "Obligaciones", "Vencidas", "Vencen en 7 días", "Enviadas o en revisión",
            "Por corregir", "Cumplimiento", "Razones de atención",
        ),
        rows=rows,
        table_name="TablaCentrosEducativos",
        widths={1: 16, 2: 40, 3: 22, 4: 22, 5: 22, 8: 19, 9: 23, 11: 18, 12: 60},
        integer_columns=(6, 7, 8, 9, 10),
        percentage_columns=(11,),
        wrap_columns=(2, 3, 4, 5, 12),
    )
    if rows:
        sheet.conditional_formatting.add(
            f"G5:G{4 + len(rows)}",
            CellIsRule(operator="greaterThan", formula=["0"], fill=PatternFill("solid", fgColor=LIGHT_RED), font=Font(color=RED, bold=True)),
        )
    return len(rows)


def _create_territorial_priority_sheet(workbook, analysis):
    rows = [
        [
            center.code, center.name, center.department, getattr(center, "district", ""),
            center.attention_label,
            "; ".join(reason["label"] for reason in center.attention_reasons),
            center.overdue_count, center.critical_active_count,
            center.automatic_no_response_count, center.correction_count,
            center.due_soon_count,
        ]
        for center in analysis["all_priority_centers"]
    ]
    sheet = _create_data_sheet(
        workbook,
        title="Prioridades",
        description="Todos los centros con alertas, ordenados por vencimientos y riesgo. Las razones explican su nivel de atención.",
        headers=(
            "Código", "Centro educativo", "Departamento", "Distrito", "Nivel de atención",
            "Razones", "Vencidas", "Riesgo crítico", "Incumplimientos automáticos",
            "Por corregir", "Vencen en 7 días",
        ),
        rows=rows,
        table_name="TablaPrioridades",
        widths={1: 16, 2: 40, 3: 22, 4: 22, 5: 22, 6: 60, 9: 27, 11: 20},
        integer_columns=(7, 8, 9, 10, 11),
        wrap_columns=(2, 3, 4, 5, 6),
    )
    if rows:
        sheet.conditional_formatting.add(
            f"E5:E{4 + len(rows)}",
            FormulaRule(formula=['$E5="Atención inmediata"'], fill=PatternFill("solid", fgColor=LIGHT_RED), font=Font(color=RED, bold=True)),
        )
    return len(rows)


def _finish_territorial_workbook(workbook, analysis, depth, report_id, counts):
    """Apply shared reading aids without changing the shared analysis metrics."""
    summary = workbook["Resumen"]
    summary["A8"] = "Tipo de análisis"
    summary.merge_cells("B8:C8")
    summary["B8"] = TERRITORIAL_EXPORT_DEPTHS[depth]
    summary["A8"].font = Font(name="Aptos", size=10, bold=True, color=NAVY)
    summary["B8"].font = Font(name="Aptos", size=10, color=NAVY)
    summary.column_dimensions["B"].width = 38
    summary.column_dimensions["D"].width = 36
    # Wrapped metadata must remain legible for long names and filter labels.
    for row in range(5, 25):
        summary.row_dimensions[row].height = 24
        for column in (1, 2, 4):
            summary.cell(row, column).alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        summary.cell(row, 5).alignment = Alignment(horizontal="right", vertical="center")

    _write_section_title(summary, 27, "Cómo leer los resultados", 8)
    explanations = [
        f"Obligaciones vencidas: {analysis['overdue_obligations']}. Centros con vencimientos: "
        f"{analysis['overdue_center_count']}. Centros con atención inmediata: {analysis['immediate_center_count']}.",
        f"Cumplimiento: {analysis['complied_obligations']} cumplidas / "
        f"{analysis['terminal_obligations']} resultados definitivos. No mide el avance de todas las obligaciones.",
        "N/D significa que no hay resultados definitivos. Un 0 % significa que hay resultados definitivos y ninguno está cumplido.",
        "La situación vigente incluye el historial consolidado y excluye borradores. La actividad del período usa la fecha propia de cada evento.",
        "Riesgos: centro auditado. Plazos y cumplimiento: institución responsable. Los vencimientos consideran la última prórroga.",
        "Los indicadores son una fotografía de la fecha de generación. Editar o filtrar las tablas en Excel no recalcula el resumen.",
    ]
    for row, value in enumerate(explanations, start=28):
        summary.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
        cell = summary.cell(row, 1, value)
        cell.font = Font(name="Aptos", size=10, color=NAVY)
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        summary.row_dimensions[row].height = 30

    _write_section_title(summary, 35, "Hojas del reporte", 8)
    for row, sheet in enumerate(workbook.worksheets[1:], start=36):
        summary.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
        cell = summary.cell(row, 1, sheet.title)
        cell.hyperlink = f"#'{sheet.title}'!A1"
        cell.font = Font(name="Aptos", size=10, color=BLUE, underline="single")
        summary.row_dimensions[row].height = 22
    last_row = 35 + len(workbook.worksheets) - 1

    if depth == "light":
        # A compact comparison keeps the light report to three sheets.
        start = last_row + 3
        _write_section_title(summary, start, "Comparación territorial", 8)
        for column, end, title in (
            (1, 3, analysis["selected_group_label"]),
            (4, 4, "Centros"), (5, 5, "Atención inmediata"), (6, 8, "Obligaciones vencidas"),
        ):
            if end > column:
                summary.merge_cells(start_row=start + 1, start_column=column, end_row=start + 1, end_column=end)
            summary.cell(start + 1, column, title)
        _style_table_header(summary[start + 1])
        summary.row_dimensions[start + 1].height = 32
        for row, territory in enumerate(analysis["territory_rows"], start=start + 2):
            summary.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
            summary.merge_cells(start_row=row, start_column=6, end_row=row, end_column=8)
            for column, value in ((1, territory["name"]), (4, territory["center_count"]), (5, territory["immediate_count"]), (6, territory["overdue_count"])):
                cell = summary.cell(row, column, _safe_text(value) if isinstance(value, str) else value)
                cell.font = Font(name="Aptos", size=10, color=NAVY)
                cell.alignment = Alignment(wrap_text=True, vertical="center")
            summary.row_dimensions[row].height = 30
        last_row = start + 1 + len(analysis["territory_rows"])
        if not analysis["territory_rows"]:
            last_row += 1
            summary.merge_cells(start_row=last_row, start_column=1, end_row=last_row, end_column=8)
            summary.cell(last_row, 1, "Sin registros para los filtros seleccionados.")

    summary.print_area = f"A1:H{last_row}"
    summary.page_setup.fitToHeight = 0
    summary.sheet_properties.tabColor = NAVY
    for sheet in workbook.worksheets[1:]:
        sheet["A3"] = "Volver al resumen"
        sheet["A3"].hyperlink = "#'Resumen'!A1"
        sheet["A3"].font = Font(name="Aptos", size=9, color=BLUE, underline="single")
        sheet.freeze_panes = "C5" if sheet.title in ("Centros educativos", "Prioridades") else "A5"
        # Explicit N/D keeps missing outcomes distinct from zero in either depth.
        for cell in sheet[4]:
            if cell.value == "Cumplimiento" and sheet.tables:
                for row in range(5, sheet.max_row + 1):
                    target = sheet.cell(row, cell.column)
                    if target.value is None and sheet.cell(row, 1).value:
                        target.value = "N/D"
        for row in sheet.iter_rows(min_row=5):
            lines = max((
                sum(max(1, ceil(len(part) / max(1, sheet.column_dimensions[cell.column_letter].width - 2))) for part in str(cell.value).split("\n"))
                for cell in row if cell.value is not None and cell.alignment.wrap_text
            ), default=1)
            sheet.row_dimensions[row[0].row].height = min(409, max(24, 15 * lines + 6))

    workbook.active = 0
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer, {"report_id": report_id, "depth": depth, "counts": counts}


def build_territorial_analysis_xlsx(
    *,
    analysis,
    generated_by,
    generated_at=None,
    depth="deep",
):
    """Render the shared territorial analysis without recalculating its metrics."""

    if depth not in TERRITORIAL_EXPORT_DEPTHS:
        raise ValueError("Tipo de análisis no válido.")
    generated_at = generated_at or timezone.now()
    report_id = f"DAI-TERR-{timezone.localtime(generated_at):%Y%m%d-%H%M%S}-{generated_by.pk}"
    workbook = Workbook()
    workbook.properties.creator = _display_user(generated_by)
    workbook.properties.lastModifiedBy = _display_user(generated_by)
    workbook.properties.title = TERRITORIAL_EXPORT_DEPTHS[depth]
    workbook.properties.subject = report_id
    workbook.properties.description = "Corte territorial generado por SIGA-MINEDUCYT."
    workbook.properties.keywords = "auditoría, centros educativos, territorio, cumplimiento, riesgo"
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.calculation.calcMode = "auto"

    _create_territorial_summary_sheet(
        workbook,
        report_id=report_id,
        analysis=analysis,
        generated_by=generated_by,
        generated_at=generated_at,
    )

    if depth == "light":
        priority_count = _create_territorial_priority_sheet(workbook, analysis)
        center_count = _create_light_center_sheet(workbook, analysis)
        return _finish_territorial_workbook(
            workbook, analysis, depth, report_id,
            {"centers": center_count, "priority_centers": priority_count, "territories": len(analysis["territory_rows"])},
        )

    territory_rows = [
        [
            row["name"],
            row["center_count"],
            row["audited_count"],
            row["coverage_rate"] / 100,
            row["immediate_count"],
            row["immediate_rate"] / 100,
            row["high_attention_count"],
            row["overdue_center_count"],
            row["critical_center_count"],
            row["without_cde_count"],
            row["without_access_count"],
            row["case_count"],
            row["obligation_count"],
            row["overdue_count"],
            row["terminal_count"],
            row["complied_count"],
            row["compliance_rate"] / 100 if row["compliance_rate"] is not None else None,
        ]
        for row in analysis["territory_rows"]
    ]
    territory_sheet = _create_data_sheet(
        workbook,
        title="Comparación territorial",
        description=(
            f"Centros agrupados por {analysis['selected_group_label'].lower()}. "
            "Los porcentajes se calculan sobre totales agregados, no como promedio de centros."
        ),
        headers=(
            analysis["selected_group_label"], "Centros", "Auditados", "Cobertura",
            "Atención inmediata", "% atención inmediata", "Prioridad alta",
            "Centros con vencimientos", "Centros con riesgo crítico", "Sin CDE vigente",
            "Sin acceso activo", "Expedientes", "Obligaciones", "Obligaciones vencidas",
            "Resultados definitivos", "Cumplidas", "Cumplimiento",
        ),
        rows=territory_rows,
        table_name="TablaComparacionTerritorial",
        widths={1: 28, 4: 14, 5: 21, 6: 21, 8: 24, 9: 24, 10: 19, 11: 18, 14: 22, 15: 22, 17: 16},
        integer_columns=(2, 3, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16),
        percentage_columns=(4, 6, 17),
    )
    if territory_rows:
        territory_sheet.conditional_formatting.add(
            f"H5:H{4 + len(territory_rows)}",
            CellIsRule(operator="greaterThan", formula=["0"], fill=PatternFill("solid", fgColor=LIGHT_RED), font=Font(color=RED, bold=True)),
        )

    center_rows = _territorial_center_rows(analysis["centers"])
    center_sheet = _create_data_sheet(
        workbook,
        title="Centros educativos",
        description=(
            "Universo de centros que coincide con los filtros. Riesgos se atribuyen al centro "
            "auditado; plazos y cumplimiento, a la institución responsable."
        ),
        headers=(
            "Código", "Centro educativo", "Departamento", "Distrito", "Municipio",
            "Nivel de atención", "Razones de atención", "Expedientes", "Expedientes activos",
            "Hallazgos", "Riesgo crítico activo", "Riesgo alto activo", "Obligaciones",
            "Vencidas", "Vencen en 7 días", "Pendientes", "Respuesta enviada", "En revisión",
            "Por corregir", "Cumplidas", "Parcialmente cumplidas", "No cumplidas",
            "Cumplimiento", "Estado del CDE", "Acceso institucional", "Último informe",
            "Última actividad",
        ),
        rows=center_rows,
        table_name="TablaCentrosEducativos",
        widths={1: 16, 2: 40, 3: 20, 4: 20, 5: 22, 6: 20, 7: 55, 23: 16, 24: 22, 25: 24, 26: 18, 27: 20},
        date_columns=(26,),
        datetime_columns=(27,),
        integer_columns=tuple(range(8, 23)),
        percentage_columns=(23,),
        wrap_columns=(2, 7),
    )
    if center_rows:
        center_sheet.conditional_formatting.add(
            f"N5:N{4 + len(center_rows)}",
            CellIsRule(operator="greaterThan", formula=["0"], fill=PatternFill("solid", fgColor=LIGHT_RED), font=Font(color=RED, bold=True)),
        )

    activity_rows = [[
        "Total del período", None,
        analysis["activity_case_count"], analysis["activity_report_count"],
        analysis["activity_finding_count"], analysis["activity_critical_count"],
        analysis["activity_recommendation_count"], analysis["activity_response_count"],
        analysis["activity_review_count"], analysis["activity_extension_count"],
        analysis["activity_automatic_no_response_count"],
    ]]
    activity_rows.extend(
        [
            "Serie mensual", row["month"], row["cases"], None, None, None, None,
            row["responses"], row["reviews"], None, None,
        ]
        for row in analysis["monthly_activity"]
    )
    _create_data_sheet(
        workbook,
        title="Actividad del período",
        description=(
            f"Actividad de {analysis['selected_period_label'].lower()}. Cada evento se incluye "
            "según su propia fecha de registro."
        ),
        headers=(
            "Alcance", "Mes", "Expedientes", "Informes", "Hallazgos", "Hallazgos críticos",
            "Recomendaciones", "Respuestas", "Dictámenes", "Prórrogas",
            "Incumplimientos automáticos",
        ),
        rows=activity_rows,
        table_name="TablaActividadPeriodo",
        widths={1: 22, 2: 16, 3: 16, 4: 14, 5: 14, 6: 21, 7: 20, 8: 15, 9: 15, 10: 14, 11: 27},
        date_columns=(2,),
        integer_columns=tuple(range(3, 12)),
    )

    priority_count = _create_territorial_priority_sheet(workbook, analysis)

    exported_counts = {
        "centers": len(center_rows),
        "territories": len(territory_rows),
        "priority_centers": priority_count,
        "activity_months": len(analysis["monthly_activity"]),
    }
    method_rows = [
        ["Control", "Centros exportados", analysis["center_count"], len(center_rows), "OK" if analysis["center_count"] == len(center_rows) else "ERROR"],
        ["Control", "Territorios exportados", len(analysis["territory_rows"]), len(territory_rows), "OK" if len(analysis["territory_rows"]) == len(territory_rows) else "ERROR"],
        ["Calidad", "Centros sin departamento", analysis["data_quality"]["without_department"], None, "Revisar catálogo" if analysis["data_quality"]["without_department"] else "OK"],
        ["Calidad", "Centros sin distrito", analysis["data_quality"]["without_district"], None, "Revisar catálogo" if analysis["data_quality"]["without_district"] else "OK"],
        ["Metodología", "Situación vigente", None, None, "Usa todo el historial consolidado y excluye borradores."],
        ["Metodología", "Actividad", None, None, "Cada evento se atribuye al período mediante su fecha propia."],
        ["Metodología", "Riesgo y hallazgos", None, None, "Se atribuyen al centro educativo auditado."],
        ["Metodología", "Plazos y cumplimiento", None, None, "Se atribuyen a la institución responsable y usan la última prórroga."],
        ["Metodología", "Sin resultados definitivos", None, None, "Se presenta como N/D; no equivale a 0 %."],
    ]
    method_sheet = _create_data_sheet(
        workbook,
        title="Calidad y metodología",
        description="Controles de integridad, calidad territorial y reglas de interpretación del informe.",
        headers=("Tipo", "Elemento", "Valor esperado", "Valor exportado", "Resultado o definición"),
        rows=method_rows,
        table_name="TablaCalidadMetodologia",
        widths={1: 18, 2: 32, 3: 18, 4: 18, 5: 70},
        integer_columns=(3, 4),
        wrap_columns=(2, 5),
        landscape=False,
    )
    method_sheet.conditional_formatting.add(
        f"E5:E{4 + len(method_rows)}",
        FormulaRule(formula=['$E5="ERROR"'], fill=PatternFill("solid", fgColor=LIGHT_RED), font=Font(color=RED, bold=True)),
    )

    return _finish_territorial_workbook(
        workbook, analysis, depth, report_id, exported_counts,
    )
