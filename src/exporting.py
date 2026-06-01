from __future__ import annotations

import datetime
from io import BytesIO

import pandas as pd


def _sanitize_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare a DataFrame for Excel export by converting problematic types.

    xlsxwriter cannot handle:
    - timezone-aware datetimes (DatetimeTZDtype) → strip tz info
    - Python datetime.date objects → convert to string 'YYYY-MM-DD'
    - bool columns → keep as-is (xlsxwriter handles bools fine)
    """
    df = df.copy()
    for col in df.columns:
        # Timezone-aware datetime column
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            if hasattr(df[col].dtype, "tz") and df[col].dtype.tz is not None:
                df[col] = df[col].dt.tz_localize(None)
        # Python-native date / datetime objects stored as object dtype
        elif df[col].dtype == object:
            sample = df[col].dropna().iloc[0] if not df[col].dropna().empty else None
            if isinstance(sample, (datetime.date, datetime.datetime)):
                df[col] = df[col].apply(
                    lambda v: v.isoformat() if isinstance(v, (datetime.date, datetime.datetime)) else v
                )
    return df


def build_excel_export(
    time_series: pd.DataFrame,
    summary_table: pd.DataFrame,
    monthly_tariff: pd.DataFrame | None = None,
    scenarios: pd.DataFrame | None = None,
) -> bytes:
    """Build an Excel workbook containing summary, time series, tariff and scenario sheets."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        _sanitize_for_excel(summary_table).to_excel(writer, sheet_name="Resumen", index=False)
        _sanitize_for_excel(time_series).to_excel(writer, sheet_name="Serie_15min", index=False)
        if monthly_tariff is not None and not monthly_tariff.empty:
            _sanitize_for_excel(monthly_tariff).to_excel(writer, sheet_name="Tarifa_GDMTH", index=False)
        if scenarios is not None and not scenarios.empty:
            _sanitize_for_excel(scenarios).to_excel(writer, sheet_name="Escenarios", index=False)

        workbook = writer.book
        header_format = workbook.add_format({"bold": True, "bg_color": "#062B49", "font_color": "#FFFFFF"})
        money_format = workbook.add_format({"num_format": "$#,##0.00"})
        number_format = workbook.add_format({"num_format": "#,##0.00"})

        for sheet_name, worksheet in writer.sheets.items():
            worksheet.freeze_panes(1, 0)
            worksheet.set_row(0, None, header_format)
            worksheet.set_column(0, 30, 16, number_format)
            if sheet_name == "Tarifa_GDMTH":
                worksheet.set_column(5, 12, 18, money_format)

    return buffer.getvalue()


def build_pdf_report(
    summary_table: pd.DataFrame,
    annual_tariff: dict[str, float] | None = None,
) -> bytes:
    """Build a compact PDF report with main simulation indicators."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=0.55 * inch, leftMargin=0.55 * inch)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Reporte de simulación fotovoltaica GDMTH", styles["Title"]))
    story.append(Paragraph("Resumen automático generado desde la aplicación Streamlit.", styles["BodyText"]))
    story.append(Spacer(1, 0.18 * inch))

    table_data = [summary_table.columns.tolist()] + summary_table.astype(str).values.tolist()
    table = Table(table_data, colWidths=[3.2 * inch, 2.3 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#062B49")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9E2EC")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FC")]),
            ]
        )
    )
    story.append(table)

    if annual_tariff:
        story.append(Spacer(1, 0.22 * inch))
        story.append(Paragraph("Estimación tarifaria", styles["Heading2"]))
        tariff_rows = [
            ["Costo anual sin PV", f"${annual_tariff['annual_cost_without_pv_mxn']:,.2f} MXN"],
            ["Costo anual con PV", f"${annual_tariff['annual_cost_with_pv_mxn']:,.2f} MXN"],
            ["Ahorro estimado", f"${annual_tariff['annual_savings_mxn']:,.2f} MXN"],
            ["Ahorro porcentual", f"{annual_tariff['annual_savings_percent']:.2f} %"],
        ]
        tariff_table = Table([["Indicador", "Valor"]] + tariff_rows, colWidths=[3.2 * inch, 2.3 * inch])
        tariff_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#062B49")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9E2EC")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FC")]),
                ]
            )
        )
        story.append(tariff_table)

    doc.build(story)
    return buffer.getvalue()
