from io import BytesIO

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from xml.sax.saxutils import escape


NAVY = colors.HexColor("#102A43")
BLUE = colors.HexColor("#145DA0")
LIGHT_BLUE = colors.HexColor("#EAF3FB")
LIGHT_GRAY = colors.HexColor("#F4F7F9")
MID_GRAY = colors.HexColor("#5F6B76")
LINE = colors.HexColor("#D7E0E8")


def _safe(value):
    return escape(str(value or ""))


def build_response_receipt(response):
    buffer = BytesIO()
    case = response.recommendation.finding.case
    recommendation = response.recommendation
    evidence = list(response.evidence.all())
    folio = f"RESP-{case.pk:06d}-{recommendation.pk:06d}-V{response.version}"

    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=22 * mm,
        bottomMargin=20 * mm,
        title=f"Constancia de respuesta {folio}",
        author="Dirección de Auditoría Interna",
        subject=case.reference,
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="Institution",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=NAVY,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReceiptTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=NAVY,
            spaceAfter=5 * mm,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Section",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=NAVY,
            spaceBefore=5 * mm,
            spaceAfter=2 * mm,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyCompact",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#17212B"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="SmallRight",
            parent=styles["Normal"],
            fontSize=8,
            leading=10,
            textColor=MID_GRAY,
            alignment=TA_RIGHT,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Footer",
            parent=styles["Normal"],
            fontSize=7.5,
            leading=10,
            textColor=MID_GRAY,
            alignment=TA_CENTER,
        )
    )
    styles.add(
        ParagraphStyle(
            name="EvidenceHeader",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.white,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Hash",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#17212B"),
        )
    )

    def page_footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(20 * mm, 14 * mm, letter[0] - 20 * mm, 14 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MID_GRAY)
        canvas.drawString(20 * mm, 9.5 * mm, folio)
        canvas.drawRightString(letter[0] - 20 * mm, 9.5 * mm, f"Página {doc.page}")
        canvas.restoreState()

    story = [
        Table(
            [
                [
                    Paragraph("MINISTERIO DE EDUCACIÓN<br/>Dirección de Auditoría Interna", styles["Institution"]),
                    Paragraph(f"<b>Folio</b><br/>{folio}", styles["SmallRight"]),
                ]
            ],
            colWidths=[120 * mm, 50 * mm],
        ),
        Spacer(1, 8 * mm),
        Paragraph("Constancia de respuesta institucional", styles["ReceiptTitle"]),
        Paragraph(
            "Este documento confirma la recepción de una respuesta y sus evidencias dentro del "
            "SIGA-MINEDUCYT.",
            styles["BodyCompact"],
        ),
        Spacer(1, 5 * mm),
    ]

    summary = [
        [Paragraph("Referencia", styles["Institution"]), Paragraph(_safe(case.reference), styles["BodyCompact"])],
        [
            Paragraph("Institución auditada", styles["Institution"]),
            Paragraph(_safe(case.audited_organization.name), styles["BodyCompact"]),
        ],
        [
            Paragraph("Institución responsable", styles["Institution"]),
            Paragraph(_safe(recommendation.responsible_organization.name), styles["BodyCompact"]),
        ],
        [
            Paragraph("Hallazgo", styles["Institution"]),
            Paragraph(
                f"{recommendation.finding.number}. {_safe(recommendation.finding.title)}",
                styles["BodyCompact"],
            ),
        ],
        [
            Paragraph("Presentación", styles["Institution"]),
            Paragraph(timezone.localtime(response.submitted_at).strftime("%d/%m/%Y %H:%M"), styles["BodyCompact"]),
        ],
    ]
    summary_table = Table(summary, colWidths=[44 * mm, 126 * mm], hAlign="LEFT")
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), LIGHT_BLUE),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend(
        [
            summary_table,
            Paragraph("Recomendación", styles["Section"]),
            Paragraph(_safe(recommendation.text), styles["BodyCompact"]),
            Paragraph("Respuesta presentada", styles["Section"]),
            Table(
                [
                    [
                        Paragraph("Estado declarado", styles["Institution"]),
                        Paragraph(_safe(response.get_declared_status_display()), styles["BodyCompact"]),
                    ],
                    [
                        Paragraph("Responsable", styles["Institution"]),
                        Paragraph(
                            f"{_safe(response.responsible_name)} - {_safe(response.responsible_job_title)}",
                            styles["BodyCompact"],
                        ),
                    ],
                    [
                        Paragraph("Acciones realizadas", styles["Institution"]),
                        Paragraph(_safe(response.action_description).replace("\n", "<br/>"), styles["BodyCompact"]),
                    ],
                ],
                colWidths=[44 * mm, 126 * mm],
                style=TableStyle(
                    [
                        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                        ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                        ("BACKGROUND", (0, 0), (0, -1), LIGHT_GRAY),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 7),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                ),
            ),
            Paragraph("Evidencias recibidas", styles["Section"]),
        ]
    )

    evidence_rows = [
        [
            Paragraph("Archivo", styles["EvidenceHeader"]),
            Paragraph("Tipo", styles["EvidenceHeader"]),
            Paragraph("Huella de integridad", styles["EvidenceHeader"]),
        ]
    ]
    for item in evidence:
        evidence_rows.append(
            [
                Paragraph(f"{_safe(item.original_filename)}<br/><font color='#5F6B76'>{_safe(item.description)}</font>", styles["BodyCompact"]),
                Paragraph(_safe(item.get_category_display()), styles["BodyCompact"]),
                Paragraph(_safe(item.sha256), styles["Hash"]),
            ]
        )
    evidence_table = Table(evidence_rows, colWidths=[70 * mm, 35 * mm, 65 * mm], repeatRows=1)
    evidence_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend(
        [
            evidence_table,
            Spacer(1, 8 * mm),
            KeepTogether(
                [
                    Paragraph(
                        "La generación de esta constancia no implica que Auditoría Interna haya validado "
                        "el cumplimiento. El resultado se determina durante la revisión correspondiente.",
                        styles["Footer"],
                    ),
                    Spacer(1, 2 * mm),
                    Paragraph(
                        f"Documento generado por el sistema el {timezone.localtime().strftime('%d/%m/%Y %H:%M')}",
                        styles["Footer"],
                    ),
                ]
            ),
        ]
    )

    document.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    buffer.seek(0)
    return buffer, folio
