from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

TEAL = colors.HexColor("#0F766E")
DEEP = colors.HexColor("#0B3B3A")


def build_report_pdf(summary):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm)
    s = getSampleStyleSheet()
    title = s["Title"]
    title.textColor = DEEP
    h = s["Heading2"]
    h.textColor = TEAL
    body = s["BodyText"]

    label = summary.get("period", "day").title()
    span = summary.get("date") or f"{summary.get('start')} to {summary.get('end')}"
    elems = [Paragraph("SentinelAQ Data-Quality Report", title),
             Paragraph(f"{label} report | {span}", body), Spacer(1, 8 * mm)]

    n = max(summary["readings"], 1)
    kpis = [["Readings", summary["readings"]],
            ["Valid", f"{summary['valid']} ({summary['valid'] / n * 100:.1f}%)"],
            ["Invalid", f"{summary['invalid']} ({summary['invalid'] / n * 100:.1f}%)"],
            ["Review", f"{summary['review']} ({summary['review'] / n * 100:.1f}%)"],
            ["Pollution events", summary["pollution_events"]],
            ["Mean confidence", summary["mean_confidence"]],
            ["Devices reporting", summary["devices_reporting"]]]
    t = Table(kpis, colWidths=[60 * mm, 100 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#ECFEFF")),
                           ("TEXTCOLOR", (0, 0), (0, -1), DEEP),
                           ("FONTSIZE", (0, 0), (-1, -1), 10),
                           ("PADDING", (0, 0), (-1, -1), 6)]))
    elems += [Paragraph("Summary", h), t, Spacer(1, 6 * mm)]

    faults = summary.get("faults_by_type") or {}
    if faults:
        rows = [["Fault type", "Count"]] + [[k, v] for k, v in faults.items()]
        ft = Table(rows, colWidths=[80 * mm, 40 * mm])
        ft.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                                ("BACKGROUND", (0, 0), (-1, 0), TEAL),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                ("FONTSIZE", (0, 0), (-1, -1), 10),
                                ("PADDING", (0, 0), (-1, -1), 5)]))
        elems += [Paragraph("Rejected readings by fault type", h), ft, Spacer(1, 6 * mm)]

    devices = summary.get("by_device") or []
    if devices:
        rows = [["Device", "City", "Invalid", "Review", "Main fault"]]
        rows += [[d["device"], d.get("city", "-"), d["invalid"], d["review"], d.get("top_fault", "-")] for d in devices]
        dt = Table(rows, colWidths=[35 * mm, 35 * mm, 25 * mm, 25 * mm, 40 * mm])
        dt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                                ("BACKGROUND", (0, 0), (-1, 0), TEAL),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                ("FONTSIZE", (0, 0), (-1, -1), 9),
                                ("PADDING", (0, 0), (-1, -1), 4)]))
        elems += [Paragraph("Anomalies by device", h), dt]

    doc.build(elems)
    return buf.getvalue()
