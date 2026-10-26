"""
PREDICTA – Report Routes: PDF maintenance report and CSV exports for both segments
"""

from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required
from datetime import datetime, timedelta
from sqlalchemy import desc
import os, io

report_bp = Blueprint("reports", __name__)


@report_bp.route("/generate/<device_id>", methods=["GET"])
@jwt_required()
def generate_report(device_id):
    """
    GET /api/reports/generate/<device_id>?days=7
    Generates a PDF maintenance report and returns download link.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                         Table, TableStyle, HRFlowable)
        from reportlab.lib.units import mm
    except ImportError:
        return jsonify({"error": "reportlab not installed. Run: pip install reportlab"}), 500

    from models import SensorReading, FaultEvent, Machine
    from database import db

    days  = int(request.args.get("days", 7))
    since = datetime.utcnow() - timedelta(days=days)

    machine  = Machine.query.filter_by(device_id=device_id).first()
    readings = (SensorReading.query
                .filter_by(device_id=device_id)
                .filter(SensorReading.timestamp >= since)
                .order_by(SensorReading.timestamp).all())
    faults   = (FaultEvent.query
                .filter_by(device_id=device_id)
                .filter(FaultEvent.occurred_at >= since)
                .order_by(desc(FaultEvent.occurred_at)).all())

    # Build PDF in memory
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=20*mm, bottomMargin=20*mm)

    styles  = getSampleStyleSheet()
    story   = []
    dark_bg = colors.HexColor("#1a1d2e")
    accent  = colors.HexColor("#00d4ff")
    danger  = colors.HexColor("#ff4444")
    warn    = colors.HexColor("#ffd700")
    ok      = colors.HexColor("#00ff88")

    # Title
    title_style = ParagraphStyle("title", fontSize=20, textColor=accent,
                                  spaceAfter=4, fontName="Helvetica-Bold")
    sub_style   = ParagraphStyle("sub", fontSize=10, textColor=colors.grey, spaceAfter=12)
    h2_style    = ParagraphStyle("h2", fontSize=13, textColor=accent,
                                  spaceBefore=12, spaceAfter=6, fontName="Helvetica-Bold")

    story.append(Paragraph("PREDICTA", title_style))
    story.append(Paragraph("AI-Based Industrial Machine Health Monitoring Report", sub_style))
    story.append(HRFlowable(width="100%", thickness=1, color=accent))
    story.append(Spacer(1, 6*mm))

    # Machine Info
    story.append(Paragraph("Machine Information", h2_style))
    machine_data = [
        ["Device ID", device_id, "Report Period", f"Last {days} days"],
        ["Name", machine.name if machine else "N/A", "Generated", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")],
        ["Location", machine.location or "N/A", "Type", machine.machine_type or "N/A"],
        ["Rated Power", f"{machine.rated_power or 1.5} kW", "Rated Current", f"{machine.rated_current or 3.5} A"],
    ] if machine else [["Device ID", device_id]]
    t = Table(machine_data, colWidths=[40*mm, 65*mm, 40*mm, 45*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#12151e")),
        ("TEXTCOLOR", (0,0), (-1,-1), colors.white),
        ("TEXTCOLOR", (0,0), (0,-1), colors.HexColor("#aaaaaa")),
        ("TEXTCOLOR", (2,0), (2,-1), colors.HexColor("#aaaaaa")),
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#2a2d3e")),
        ("PADDING", (0,0), (-1,-1), 6),
        ("FONTSIZE", (0,0), (-1,-1), 9),
    ]))
    story.append(t)
    story.append(Spacer(1, 6*mm))

    # Summary Statistics
    if readings:
        avg_health = sum(r.health_score or 0 for r in readings) / len(readings)
        avg_temp   = sum(r.motor_temp or 0 for r in readings) / len(readings)
        avg_curr   = sum(r.current or 0 for r in readings) / len(readings)
        avg_vib    = sum(r.vibration_rms or 0 for r in readings) / len(readings)
        max_temp   = max(r.motor_temp or 0 for r in readings)
        max_curr   = max(r.current or 0 for r in readings)

        story.append(Paragraph("Performance Summary", h2_style))
        summary_data = [
            ["Parameter", "Average", "Peak", "Status"],
            ["Health Score", f"{avg_health:.1f}%", "-", "GOOD" if avg_health > 80 else "WARN"],
            ["Motor Temperature (°C)", f"{avg_temp:.1f}", f"{max_temp:.1f}", "GOOD" if avg_temp < 75 else "WARN"],
            ["Current (A)", f"{avg_curr:.2f}", f"{max_curr:.2f}", "GOOD" if max_curr < 4.5 else "WARN"],
            ["Vibration (g RMS)", f"{avg_vib:.3f}", "-", "GOOD" if avg_vib < 0.5 else "WARN"],
            ["Total Readings", str(len(readings)), "-", "-"],
            ["Total Faults", str(len(faults)), "-", "GOOD" if len(faults) == 0 else "WARN"],
        ]
        ts = Table(summary_data, colWidths=[70*mm, 40*mm, 40*mm, 40*mm])
        ts.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0d1117")),
            ("TEXTCOLOR", (0,0), (-1,0), accent),
            ("BACKGROUND", (0,1), (-1,-1), colors.HexColor("#12151e")),
            ("TEXTCOLOR", (0,1), (-1,-1), colors.white),
            ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#2a2d3e")),
            ("PADDING", (0,0), (-1,-1), 6),
            ("FONTSIZE", (0,0), (-1,-1), 9),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ]))
        story.append(ts)
        story.append(Spacer(1, 6*mm))

    # Fault Events
    story.append(Paragraph("Fault Events", h2_style))
    if faults:
        fault_data = [["#", "Fault Type", "Severity", "Timestamp", "RUL (days)"]]
        for i, f in enumerate(faults[:20], 1):
            fault_data.append([
                str(i), f.fault_type or "-", f.severity or "-",
                f.occurred_at.strftime("%Y-%m-%d %H:%M"),
                str(round(f.rul_days, 1)) if f.rul_days else "-"
            ])
        tf = Table(fault_data, colWidths=[10*mm, 60*mm, 30*mm, 50*mm, 30*mm])
        tf.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0d1117")),
            ("TEXTCOLOR", (0,0), (-1,0), accent),
            ("BACKGROUND", (0,1), (-1,-1), colors.HexColor("#12151e")),
            ("TEXTCOLOR", (0,1), (-1,-1), colors.white),
            ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#2a2d3e")),
            ("PADDING", (0,0), (-1,-1), 5),
            ("FONTSIZE", (0,0), (-1,-1), 8),
        ]))
        story.append(tf)
    else:
        story.append(Paragraph("✅ No fault events recorded in this period.", styles["Normal"]))

    story.append(Spacer(1, 8*mm))
    story.append(Paragraph("This report was automatically generated by PREDICTA AI-Based Predictive Maintenance System.", sub_style))

    doc.build(story)
    buf.seek(0)

    filename = f"predicta_report_{device_id}_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=True, download_name=filename)


# ─── CSV exports ──────────────────────────────────────────────────────────────

def _csv_response(rows, header, filename):
    import csv
    from flask import Response
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@report_bp.route("/telemetry/<device_id>.csv", methods=["GET"])
@jwt_required()
def export_telemetry_csv(device_id):
    """GET /api/reports/telemetry/<device_id>.csv?days=7 – Segment B raw telemetry export."""
    from models import SensorReading
    days = min(int(request.args.get("days", 7)), 365)
    since = datetime.utcnow() - timedelta(days=days)
    readings = (SensorReading.query.filter_by(device_id=device_id)
                .filter(SensorReading.timestamp >= since)
                .order_by(SensorReading.timestamp).limit(200000).all())
    fields = ["timestamp", "voltage", "current", "power_kw", "motor_temp", "bearing_temp", "ambient_temp",
              "humidity", "vibration_rms", "rpm", "pressure", "run_hours", "motor_running",
              "overload", "overheat", "high_vibration", "health_score", "efficiency"]
    rows = [[r.to_dict().get(f) for f in fields] for r in readings]
    return _csv_response(rows, fields, f"predicta_telemetry_{device_id}_{days}d.csv")


@report_bp.route("/analysis/<int:analysis_id>.csv", methods=["GET"])
@jwt_required()
def export_analysis_csv(analysis_id):
    """GET /api/reports/analysis/<id>.csv – Segment A analysis run: risk, violations, forecast, hypotheses."""
    from models import AnalysisRun
    run = AnalysisRun.query.get_or_404(analysis_id)
    d = run.to_dict()
    layers = d.get("layer_results", {})
    risk = layers.get("layer5_risk", {})
    l4 = layers.get("layer4_rul", {})
    forecast = l4.get("trend_forecast") or {}

    rows = [
        ["summary", "asset_id", d["asset_id"], ""],
        ["summary", "rows_analyzed", d["rows_analyzed"], ""],
        ["summary", "risk_category", d["overall_risk_category"], ""],
        ["summary", "risk_score", d["overall_risk_score"], ""],
        ["summary", "recommended_action", risk.get("recommended_action", ""), ""],
        ["summary", "remaining_useful_life_hours", l4.get("rul_hours"), l4.get("message") or l4.get("method") or ""],
    ]
    for name, value in (risk.get("contributing_weights") or {}).items():
        rows.append(["risk_inputs", name, value, ""])
    for v in layers.get("layer1_rules", {}).get("violations", []):
        rows.append(["rule_violation", v["variable"], v["level"], f"{v['rule']} ({v['percentage']}% of running samples)"])
    for v in forecast.get("variables", []):
        rows.append(["trend_forecast", v["variable"], v.get("status"),
                     f"slope {v.get('slope_per_hour')}/h, to warning {v.get('hours_to_warning')} h, "
                     f"to critical {v.get('hours_to_critical')} h"])
    for var, cp in (layers.get("changepoints") or {}).items():
        if cp.get("ongoing_shift"):
            rows.append(["changepoint", var, "ongoing shift", cp.get("ongoing_shift_timestamp") or cp.get("ongoing_shift_row")])
    for h in d.get("hypotheses", []):
        rows.append(["hypothesis", h["hypothesis"], h["confidence"],
                     " | ".join(h.get("supporting_evidence", [])) + " || Actions: " + " | ".join(h.get("recommended_actions", []))])
    return _csv_response(rows, ["section", "item", "value", "detail"], f"predicta_analysis_{analysis_id}.csv")
