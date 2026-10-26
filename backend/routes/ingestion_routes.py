"""
PREDICTA 2.0 – File Ingestion & Tag Mapping API Routes
Endpoints for uploading industrial CSV/Excel files, previewing datasets,
managing tag mapping profiles, and triggering layered AI analyses.
"""

import os
import json
import werkzeug
import numpy as np
import pandas as pd
from datetime import datetime
from flask import Blueprint, request, jsonify, send_from_directory, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity


from database import db
from models import DatasetUpload, TagMapping, AnalysisRun, Machine, SensorReading
from ingestion import (
    read_industrial_file, detect_timestamp_column, suggest_tag_mappings,
    analyze_data_quality, generate_dataset_preview, STANDARD_VARIABLES, get_excel_sheets
)
from analytics_engine import compute_time_series_features, compute_changepoints, TREND_VARIABLES
from ai_engine import (
    evaluate_layer1_rules, run_layer2_unsupervised_detection,
    run_layer3_supervised_prediction, evaluate_layer4_rul, compute_layer5_risk_score,
    merged_limits, has_run_to_failure_history, alarm_rate_pct
)
from trend_forecast import forecast_time_to_limits, trend_risk_score
from investigation import generate_fault_hypotheses
from notifications import dispatch_machine_alert

ingestion_bp = Blueprint("ingestion", __name__)


@ingestion_bp.route("/upload", methods=["POST"])
@jwt_required()
def upload_file():
    """
    POST /api/ingest/upload
    Accepts CSV, XLSX, or XLS file.
    Validates file, parses metadata, computes data quality score, and suggests tag mappings.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
        
    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"error": "Empty filename"}), 400
        
    filename = werkzeug.utils.secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in [".csv", ".xlsx", ".xls"]:
        return jsonify({"error": f"Unsupported file type '{ext}'. Only CSV, XLSX, and XLS supported."}), 400
        
    upload_dir = current_app.config.get("UPLOAD_FOLDER", os.path.join(os.path.dirname(__file__), "..", "uploads"))
    os.makedirs(upload_dir, exist_ok=True)
    
    unique_name = f"{int(datetime.utcnow().timestamp())}_{filename}"
    saved_path = os.path.join(upload_dir, unique_name)
    file.save(saved_path)
    file_size = os.path.getsize(saved_path)
    
    sheet_name = request.form.get("sheet_name")
    
    try:
        # Check excel sheets if excel
        sheets = get_excel_sheets(saved_path) if ext in [".xlsx", ".xls"] else []
        selected_sheet = sheet_name if sheet_name in sheets else (sheets[0] if sheets else None)
        
        df = read_industrial_file(saved_path, sheet_name=selected_sheet)
        
        # Detect timestamp
        ts_col, parsed_ts, sampling_rate = detect_timestamp_column(df)
        
        # Analyze Data Quality
        quality_res = analyze_data_quality(df, timestamp_col=ts_col)
        # Remembered so the analysis reads the same sheet (stored in the JSON report
        # rather than a new column, which would need a migration on existing databases).
        quality_res["sheet_name"] = selected_sheet

        # Generate Preview
        preview_res = generate_dataset_preview(df, max_rows=15)
        
        # Suggest Tag Mappings
        suggested_mappings = suggest_tag_mappings(df)
        
        # Detect Asset IDs
        detected_assets = []
        detected_asset_id = "ASSET-01"
        asset_col = suggested_mappings.get("asset_id")
        if asset_col and asset_col in df.columns:
            detected_assets = [str(a) for a in df[asset_col].dropna().unique().tolist()[:20]]
            if detected_assets:
                detected_asset_id = detected_assets[0]
        else:
            # Check filename for hints
            clean_stem = os.path.splitext(filename)[0].upper()
            detected_asset_id = clean_stem if len(clean_stem) <= 30 else "ASSET-01"
            detected_assets = [detected_asset_id]
            
        time_start = None
        time_end = None
        if ts_col and parsed_ts is not None and len(parsed_ts.dropna()) > 0:
            valid_ts = parsed_ts.dropna().sort_values()
            time_start = valid_ts.iloc[0].to_pydatetime()
            time_end = valid_ts.iloc[-1].to_pydatetime()

        # Save record in DB
        record = DatasetUpload(
            filename=filename,
            file_path=saved_path,
            file_type=ext.lstrip("."),
            file_size_bytes=file_size,
            uploaded_at=datetime.utcnow(),
            row_count=len(df),
            column_count=len(df.columns),
            columns_json=json.dumps(preview_res["columns"]),
            detected_asset_id=detected_asset_id,
            detected_assets_json=json.dumps(detected_assets),
            timestamp_column=ts_col,
            sampling_rate_seconds=sampling_rate,
            time_range_start=time_start,
            time_range_end=time_end,
            quality_score=quality_res["score"],
            quality_report_json=json.dumps(quality_res),
            status="UPLOADED"
        )
        db.session.add(record)
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "dataset_id": record.id,
            "filename": filename,
            "excel_sheets": sheets,
            "selected_sheet": selected_sheet,
            "row_count": len(df),
            "column_count": len(df.columns),
            "detected_asset_id": detected_asset_id,
            "detected_assets": detected_assets,
            "timestamp_column": ts_col,
            "sampling_rate_seconds": sampling_rate,
            "quality": quality_res,
            "preview": preview_res,
            "suggested_mappings": suggested_mappings,
            "standard_variables": STANDARD_VARIABLES
        }), 201
        
    except Exception as e:
        if os.path.exists(saved_path):
            try: os.remove(saved_path)
            except: pass
        return jsonify({"error": f"Failed to parse industrial file: {str(e)}"}), 400


@ingestion_bp.route("/datasets", methods=["GET"])
@jwt_required()
def list_datasets():
    """GET /api/ingest/datasets – List all uploaded datasets."""
    datasets = DatasetUpload.query.order_by(DatasetUpload.uploaded_at.desc()).limit(50).all()
    return jsonify([d.to_dict() for d in datasets]), 200


@ingestion_bp.route("/datasets/<int:dataset_id>", methods=["GET"])
@jwt_required()
def get_dataset(dataset_id):
    """GET /api/ingest/datasets/<id> – Retrieve dataset details and preview."""
    dataset = DatasetUpload.query.get_or_404(dataset_id)
    return jsonify(dataset.to_dict()), 200


@ingestion_bp.route("/mappings", methods=["GET", "POST"])
@jwt_required()
def handle_mappings():
    """GET or POST tag mapping profiles for reuse."""
    if request.method == "GET":
        mappings = TagMapping.query.order_by(TagMapping.name.asc()).all()
        return jsonify([m.to_dict() for m in mappings]), 200
        
    data = request.get_json() or {}
    name = data.get("name")
    mapping_dict = data.get("mapping", {})
    
    if not name or not mapping_dict:
        return jsonify({"error": "Profile name and mapping dictionary required"}), 400
        
    existing = TagMapping.query.filter_by(name=name).first()
    if existing:
        existing.mapping_json = json.dumps(mapping_dict)
        existing.description = data.get("description", existing.description)
        existing.asset_type = data.get("asset_type", existing.asset_type)
        existing.units_json = json.dumps(data.get("units", {}))
        existing.limits_json = json.dumps(data.get("limits", {}))
        db.session.commit()
        return jsonify(existing.to_dict()), 200
    else:
        new_map = TagMapping(
            name=name,
            description=data.get("description", ""),
            asset_type=data.get("asset_type", "general"),
            mapping_json=json.dumps(mapping_dict),
            units_json=json.dumps(data.get("units", {})),
            limits_json=json.dumps(data.get("limits", {}))
        )
        db.session.add(new_map)
        db.session.commit()
        return jsonify(new_map.to_dict()), 201


@ingestion_bp.route("/analyze/<int:dataset_id>", methods=["POST"])
@jwt_required()
def run_dataset_analysis(dataset_id):
    """
    POST /api/ingest/analyze/<dataset_id>
    Runs 5-layer time-series analysis, anomaly detection, risk evaluation, and hypothesis generation.
    Body:
      {
        "asset_id": "MOTOR-01",
        "mapping": {"timestamp": "Time", "motor_temp": "Temp", ...},
        "limits": {"motor_temp": {"warn": 75, "crit": 85}},
        "trigger_notifications": false
      }
    """
    dataset = DatasetUpload.query.get_or_404(dataset_id)
    data = request.get_json() or {}
    
    asset_id = data.get("asset_id") or dataset.detected_asset_id or "ASSET-01"
    mapping = data.get("mapping")
    custom_limits = data.get("limits")
    trigger_notifications = bool(data.get("trigger_notifications", False))
    
    if not os.path.exists(dataset.file_path):
        return jsonify({"error": "Dataset file missing from server storage"}), 404
        
    try:
        quality_report = json.loads(dataset.quality_report_json) if dataset.quality_report_json else {}
        df = read_industrial_file(dataset.file_path, sheet_name=quality_report.get("sheet_name"))

        # If no mapping passed, use auto-suggested
        if not mapping:
            mapping = suggest_tag_mappings(df)
            
        # Filter by asset_id if multi-asset column present
        asset_col = mapping.get("asset_id")
        if asset_col and asset_col in df.columns:
            df = df[df[asset_col].astype(str) == str(asset_id)].copy()
            if len(df) == 0:
                return jsonify({"error": f"No records found for asset_id '{asset_id}'"}), 404

        ts_col = mapping.get("timestamp")
        limits = merged_limits(custom_limits)
        label_col = "_std_failure_label" if mapping.get("failure_label") else None

        # 1. Feature Engineering & Time-Series Analytics
        features_df = compute_time_series_features(df, mapping=mapping, rolling_window=15)

        # 1b. CUSUM change-points: when did behaviour shift?
        changepoints = compute_changepoints(features_df, timestamp_col=ts_col)

        # 2. Layer 1: Engineering Rules
        l1_res = evaluate_layer1_rules(features_df, custom_limits=custom_limits)

        # 3. Layer 2: Unsupervised Anomaly Detection (Isolation Forest)
        l2_res = run_layer2_unsupervised_detection(
            features_df, contamination=current_app.config.get("ISOLATION_FOREST_CONTAMINATION", 0.03))

        # 4. Layer 3: Supervised Failure Prediction (if labels exist)
        l3_res = run_layer3_supervised_prediction(features_df, label_col=label_col)

        # 5. Layer 4: Trend forecast to engineering limits + RUL when run-to-failure history exists
        forecast = forecast_time_to_limits(features_df, limits, timestamp_col=ts_col)
        l4_res = evaluate_layer4_rul(
            features_df,
            has_run_to_failure=has_run_to_failure_history(features_df, label_col),
            trend_forecast=forecast,
            timestamp_col=ts_col,
        )

        # 6. Layer 5: Composite Health Risk Classifier
        risk_res = compute_layer5_risk_score(
            l1_res, l2_res, l3_res,
            data_quality_score=dataset.quality_score,
            trend_score=trend_risk_score(forecast),
            alarm_rate=alarm_rate_pct(features_df, mapping.get("fault_code")),
        )

        # 7. Explainable Fault Investigation Hypotheses (all 9 signatures)
        hypotheses = generate_fault_hypotheses(features_df, mapping, l1_res, l2_res, risk_res, changepoints=changepoints)

        # Build analysis summary
        if l3_res.get("available"):
            pr_auc = l3_res["metrics"].get("pr_auc")
            supervised_line = f"Trained on past, tested on future (PR-AUC {pr_auc})" if pr_auc is not None else \
                "Trained on past, tested on future (PR-AUC undefined: single class in test period)"
        else:
            supervised_line = "Unsupervised mode (no validated failure labels)"

        if l4_res.get("available"):
            rul_line = (f"{l4_res['rul_hours']} h until the level at which past failures began "
                        f"(driven by {l4_res['driving_variable']})")
        else:
            rul_line = l4_res.get("message", "Unavailable")

        earliest = forecast.get("earliest_critical")
        if earliest:
            trend_line = (f"{earliest['variable']} reaches its critical limit ({earliest['limit']} {earliest['unit']}) "
                          f"in ~{earliest['hours']} h if the current trend continues")
        elif forecast.get("available"):
            trend_line = "No variable is trending toward a critical limit within the forecast horizon"
        else:
            trend_line = forecast.get("reason", "Unavailable")

        shifted = [f"{var} ({cp['first_timestamp'] or 'row ' + str(cp['first_row'])})"
                   for var, cp in changepoints.items() if cp.get("count")]
        applicable = [h["hypothesis"] for h in hypotheses if h.get("applicable")]

        summary_md = (
            f"### Analysis Run Summary for {asset_id}\n\n"
            f"- **Overall Risk Category:** {risk_res['risk_category']} (Score: {risk_res['risk_score']}/100)\n"
            f"- **Total Rows Analyzed:** {len(features_df):,} records ({l1_res.get('samples_evaluated', 0):,} while running)\n"
            f"- **Rule Violations Detected:** {l1_res['critical_violations']} Critical, {l1_res['warning_violations']} Warning\n"
            f"- **Unsupervised Anomalies:** {l2_res.get('anomaly_count', 0)} ({l2_res.get('anomaly_rate_pct', 0.0)}% of running data)\n"
            f"- **Behaviour Change-Points (CUSUM):** {', '.join(shifted) if shifted else 'None detected'}\n"
            f"- **Supervised Failure Model:** {supervised_line}\n"
            f"- **Trend Forecast:** {trend_line}\n"
            f"- **Remaining Useful Life:** {rul_line}\n"
            f"- **Fault Signatures Evaluated:** {len(hypotheses)} ({len(applicable)} supported by the data)\n\n"
            f"**Recommended Human Action:** {risk_res['recommended_action']}"
        )

        # Save AnalysisRun to DB
        analysis_record = AnalysisRun(
            dataset_id=dataset.id,
            asset_id=asset_id,
            status="COMPLETED",
            created_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            rows_analyzed=len(features_df),
            time_start=dataset.time_range_start,
            time_end=dataset.time_range_end,
            overall_risk_category=risk_res["risk_category"],
            overall_risk_score=risk_res["risk_score"],
            anomaly_count=l2_res.get("anomaly_count", 0),
            layer_results_json=json.dumps({
                "layer1_rules": l1_res,
                "layer2_unsupervised": l2_res,
                "layer3_supervised": l3_res,
                "layer4_rul": l4_res,
                "layer5_risk": risk_res,
                "changepoints": changepoints
            }),
            hypotheses_json=json.dumps(hypotheses),
            summary_markdown=summary_md
        )
        db.session.add(analysis_record)
        dataset.status = "ANALYZED"
        db.session.commit()

        # Update or register Machine in fleet registry
        mach = Machine.query.filter_by(device_id=asset_id).first()
        if not mach:
            mach = Machine(
                device_id=asset_id,
                name=f"Asset {asset_id}",
                machine_type="Industrial Asset",
                is_active=True
            )
            db.session.add(mach)
            db.session.commit()

        # Extract downsampled trend chart series (max 200 data points for UI)
        chart_step = max(1, len(features_df) // 200)
        sampled = features_df.iloc[::chart_step]
        ts_vals = sampled[ts_col].astype(str).tolist() if ts_col in sampled.columns else list(range(len(sampled)))

        charts_data = {
            "timestamps": ts_vals,
            "variables": {}
        }
        for k in TREND_VARIABLES:
            std_k = f"_std_{k}"
            if std_k in sampled.columns:
                charts_data["variables"][k] = [
                    round(float(v), 2) if pd.notnull(v) else None for v in sampled[std_k]
                ]

        # Dispatch notification if alert worthy and enabled
        notification_outcome = None
        if risk_res["risk_category"] in ["WARNING", "CRITICAL"]:
            top_evidence = [v["rule"] for v in l1_res.get("violations", [])[:3]]
            notification_outcome = dispatch_machine_alert(
                asset_id=asset_id,
                severity=risk_res["risk_category"],
                title=f"Industrial Risk Elevated ({risk_res['risk_category']})",
                evidence=top_evidence,
                suggested_action=risk_res["recommended_action"],
                is_historical=not trigger_notifications  # if trigger_notifications is True, treated as explicit replay
            )

        return jsonify({
            "status": "success",
            "analysis_id": analysis_record.id,
            "asset_id": asset_id,
            "risk": risk_res,
            "layer1_rules": l1_res,
            "layer2_unsupervised": l2_res,
            "layer3_supervised": l3_res,
            "layer4_rul": l4_res,
            "trend_forecast": forecast,
            "changepoints": changepoints,
            "hypotheses": hypotheses,
            "summary_markdown": summary_md,
            "charts": charts_data,
            "notification_status": notification_outcome
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Analysis failed: {str(e)}"}), 500


@ingestion_bp.route("/analyses", methods=["GET"])
@jwt_required()
def list_analysis_runs():
    """GET /api/ingest/analyses?limit=10 – Recent Segment A analysis runs (summary only)."""
    limit = max(1, min(request.args.get("limit", 10, type=int), 100))
    runs = AnalysisRun.query.order_by(AnalysisRun.created_at.desc()).limit(limit).all()
    return jsonify([{
        "id": r.id,
        "dataset_id": r.dataset_id,
        "filename": r.dataset.filename if r.dataset else None,
        "asset_id": r.asset_id,
        "risk_category": r.overall_risk_category,
        "risk_score": r.overall_risk_score,
        "rows_analyzed": r.rows_analyzed,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in runs]), 200


@ingestion_bp.route("/analysis/<int:analysis_id>", methods=["GET"])
@jwt_required()
def get_analysis_run(analysis_id):
    """GET /api/ingest/analysis/<id> – Retrieve stored analysis run results."""
    run = AnalysisRun.query.get_or_404(analysis_id)
    return jsonify(run.to_dict()), 200


@ingestion_bp.route("/samples", methods=["GET"])
def list_samples():
    """List downloadable industrial demo datasets."""
    sample_dir = os.path.join(os.path.dirname(__file__), "..", "sample_data")
    if not os.path.exists(sample_dir):
        return jsonify([]), 200
        
    samples = []
    descriptions = {
        "motor_cooling_failure.csv": "3-Phase Motor with progressive cooling degradation & overcurrent",
        "pump_cavitation_anomaly.csv": "Centrifugal Pump with suction cavitation, erratic pressure, & flow loss",
        "gearbox_vibration_wear.csv": "Helical Gearbox with lubrication breakdown & rising vibration RMS",
        "compressor_valve_degradation.xlsx": "Industrial Air Compressor with discharge overheating & valve leakage"
    }
    
    for f in os.listdir(sample_dir):
        fp = os.path.join(sample_dir, f)
        if os.path.isfile(fp):
            samples.append({
                "filename": f,
                "file_size_bytes": os.path.getsize(fp),
                "description": descriptions.get(f, "Industrial PLC/SCADA simulation dataset"),
                "download_url": f"/api/ingest/download-sample/{f}"
            })
    return jsonify(samples), 200


@ingestion_bp.route("/download-sample/<filename>", methods=["GET"])
def download_sample(filename):
    """Download demo CSV or Excel file."""
    sample_dir = os.path.join(os.path.dirname(__file__), "..", "sample_data")
    return send_from_directory(sample_dir, filename, as_attachment=True)
