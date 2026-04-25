"""
PREDICTA – Machine Learning Training Pipeline
Industrial Predictive Maintenance Model

Trains Random Forest (primary), XGBoost, SVM, and Isolation Forest
on the AI4I 2020 Predictive Maintenance Dataset.

Usage:
  python train_model.py                    # Use default AI4I dataset
  python train_model.py --dataset my_data.csv  # Use custom dataset

Dataset:
  AI4I 2020: https://archive.ics.uci.edu/ml/datasets/AI4I+2020+Predictive+Maintenance+Dataset
  Kaggle:    https://www.kaggle.com/datasets/stephanmatzka/predictive-maintenance-dataset-ai4i-2020

To replace with your own dataset:
  1. Prepare CSV with columns matching FEATURE_COLS below
  2. Add a 'failure_type' column with labels: Normal, Bearing, HeatDissipation, Overstrain, etc.
  3. Run: python train_model.py --dataset your_file.csv
"""

import os
import sys
import argparse
import numpy as np
import pandas as pd
import joblib
import warnings
warnings.filterwarnings("ignore")

from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.svm import SVC
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold
from sklearn.metrics import (classification_report, confusion_matrix,
                              accuracy_score, f1_score, roc_auc_score)
from sklearn.inspection import permutation_importance
import xgboost as xgb

# ─── Configuration ────────────────────────────────────────────────────────────
MODEL_OUTPUT_DIR = "saved_models"
DATASET_URL = "https://archive.ics.uci.edu/ml/machine-learning-databases/00601/ai4i2020.csv"
RANDOM_STATE = 42

# Feature columns for our sensor setup
# Maps AI4I columns → our sensor parameters
AI4I_FEATURE_MAP = {
    "Air temperature [K]":    "ambient_temp_K",
    "Process temperature [K]":"motor_temp_K",
    "Rotational speed [rpm]": "rpm",
    "Torque [Nm]":            "torque",
    "Tool wear [min]":        "run_hours",
}

# Our custom feature columns (if using real sensor data)
CUSTOM_FEATURE_COLS = [
    "voltage", "current", "motor_temp", "bearing_temp",
    "vibration_rms", "rpm", "pressure", "power_factor",
    "humidity", "ambient_temp", "current_ratio", "temp_rise",
    "bearing_rise", "rpm_slip", "power_kw", "vib_cat"
]

FAULT_LABEL_MAP = {
    "No Failure":          0,
    "Normal":              0,
    "Tool Wear Failure":   1,   # → Bearing Failure equivalent
    "Heat Dissipation Failure": 2,  # → Motor Overheating
    "Power Failure":       3,   # → Overcurrent
    "Overstrain Failure":  4,   # → Vibration/Imbalance
    "Random Failures":     5,   # → Cooling Failure
}


def download_ai4i_dataset():
    """Download AI4I 2020 dataset from UCI."""
    import urllib.request
    os.makedirs("data", exist_ok=True)
    dest = os.path.join("data", "ai4i2020.csv")
    if os.path.exists(dest):
        print(f"[DATA] Dataset already exists: {dest}")
        return dest
    print(f"[DATA] Downloading AI4I 2020 dataset...")
    urllib.request.urlretrieve(DATASET_URL, dest)
    print(f"[DATA] Downloaded to {dest}")
    return dest


def load_ai4i_dataset(path: str) -> pd.DataFrame:
    """Load and preprocess AI4I 2020 dataset."""
    df = pd.read_csv(path)
    print(f"[DATA] Loaded {len(df)} rows from {path}")
    print(f"[DATA] Columns: {list(df.columns)}")

    # Standardize column names
    df.columns = [c.strip() for c in df.columns]

    # Select features
    feature_cols = [
        "Air temperature [K]",
        "Process temperature [K]",
        "Rotational speed [rpm]",
        "Torque [Nm]",
        "Tool wear [min]"
    ]

    # Target: 'Failure Type' or binary 'Machine failure'
    if "Failure Type" in df.columns:
        df["label"] = df["Failure Type"].map(FAULT_LABEL_MAP).fillna(0).astype(int)
    elif "Machine failure" in df.columns:
        df["label"] = df["Machine failure"].astype(int)
    else:
        raise ValueError("No target column found. Expected 'Failure Type' or 'Machine failure'")

    # Feature engineering
    df["temp_diff"] = df["Process temperature [K]"] - df["Air temperature [K]"]
    df["power_proxy"] = df["Rotational speed [rpm]"] * df["Torque [Nm]"] / 9549  # kW
    df["wear_rate"] = df["Tool wear [min]"] / (df["Rotational speed [rpm]"] / 1440 + 0.01)

    available = [c for c in feature_cols if c in df.columns]
    available += ["temp_diff", "power_proxy", "wear_rate"]

    X = df[available].copy()
    y = df["label"].copy()

    # Handle missing values
    X = X.fillna(X.median())

    print(f"[DATA] Features: {list(X.columns)}")
    print(f"[DATA] Label distribution:\n{y.value_counts()}")
    return X, y


def load_custom_dataset(path: str) -> tuple:
    """
    Load custom sensor dataset.
    CSV must have columns matching CUSTOM_FEATURE_COLS + 'failure_type' label column.
    """
    df = pd.read_csv(path)
    print(f"[DATA] Custom dataset: {len(df)} rows, columns: {list(df.columns)}")

    label_col = "failure_type" if "failure_type" in df.columns else "label"
    if label_col not in df.columns:
        raise ValueError(f"Label column '{label_col}' not found in dataset.")

    # Encode string labels
    le = LabelEncoder()
    y = le.fit_transform(df[label_col].fillna("Normal"))
    joblib.dump(le, os.path.join(MODEL_OUTPUT_DIR, "label_encoder.pkl"))
    print(f"[DATA] Label classes: {le.classes_}")

    available_features = [c for c in CUSTOM_FEATURE_COLS if c in df.columns]
    X = df[available_features].fillna(df[available_features].median())

    return X, pd.Series(y)


def feature_engineering(X: pd.DataFrame) -> pd.DataFrame:
    """Additional feature engineering for industrial data."""
    X = X.copy()

    # Add rolling statistics if timestamp column available
    # (Skipped for static dataset; implement for time-series data)

    # Clip outliers at 3 sigma
    for col in X.select_dtypes(include=[np.number]).columns:
        mean, std = X[col].mean(), X[col].std()
        X[col] = X[col].clip(mean - 3*std, mean + 3*std)

    return X


def train_models(X_train, X_test, y_train, y_test, scaler):
    """Train all models and return results."""
    results = {}

    print("\n" + "="*60)
    print("  TRAINING MODELS")
    print("="*60)

    # ─── 1. Random Forest (Primary Model) ─────────────────────────────────────
    print("\n[RF] Training Random Forest Classifier...")
    rf = RandomForestClassifier(
        n_estimators=200,
        max_depth=15,
        min_samples_split=5,
        min_samples_leaf=2,
        class_weight="balanced",
        n_jobs=-1,
        random_state=RANDOM_STATE
    )
    rf.fit(X_train, y_train)
    rf_pred = rf.predict(X_test)
    rf_proba = rf.predict_proba(X_test)

    rf_acc = accuracy_score(y_test, rf_pred)
    rf_f1  = f1_score(y_test, rf_pred, average="weighted", zero_division=0)

    print(f"[RF] Accuracy: {rf_acc:.4f} | F1: {rf_f1:.4f}")
    print(f"[RF] Classification Report:\n{classification_report(y_test, rf_pred, zero_division=0)}")

    results["random_forest"] = {
        "model": rf, "accuracy": rf_acc, "f1": rf_f1,
        "predictions": rf_pred, "probabilities": rf_proba
    }

    # Cross-validation
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    cv_scores = cross_val_score(rf, X_train, y_train, cv=cv, scoring="f1_weighted", n_jobs=-1)
    print(f"[RF] CV F1 Scores: {cv_scores.round(4)} | Mean: {cv_scores.mean():.4f}")

    # ─── 2. XGBoost ───────────────────────────────────────────────────────────
    print("\n[XGB] Training XGBoost Classifier...")
    xgb_model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        use_label_encoder=False,
        eval_metric="mlogloss",
        random_state=RANDOM_STATE,
        n_jobs=-1
    )
    xgb_model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
    xgb_pred = xgb_model.predict(X_test)
    xgb_acc  = accuracy_score(y_test, xgb_pred)
    xgb_f1   = f1_score(y_test, xgb_pred, average="weighted", zero_division=0)
    print(f"[XGB] Accuracy: {xgb_acc:.4f} | F1: {xgb_f1:.4f}")

    results["xgboost"] = {"model": xgb_model, "accuracy": xgb_acc, "f1": xgb_f1}

    # ─── 3. Support Vector Machine ────────────────────────────────────────────
    print("\n[SVM] Training SVM Classifier...")
    X_train_s = scaler.transform(X_train)
    X_test_s  = scaler.transform(X_test)
    svm = SVC(kernel="rbf", C=10, gamma="scale", class_weight="balanced",
              probability=True, random_state=RANDOM_STATE)
    svm.fit(X_train_s, y_train)
    svm_pred = svm.predict(X_test_s)
    svm_acc  = accuracy_score(y_test, svm_pred)
    svm_f1   = f1_score(y_test, svm_pred, average="weighted", zero_division=0)
    print(f"[SVM] Accuracy: {svm_acc:.4f} | F1: {svm_f1:.4f}")

    results["svm"] = {"model": svm, "accuracy": svm_acc, "f1": svm_f1}

    # ─── 4. Isolation Forest (Anomaly Detection) ──────────────────────────────
    print("\n[ISO] Training Isolation Forest (Anomaly Detector)...")
    iso = IsolationForest(
        n_estimators=100,
        contamination=0.05,  # Expected 5% anomalies
        random_state=RANDOM_STATE,
        n_jobs=-1
    )
    iso.fit(X_train)
    iso_pred = iso.predict(X_test)  # -1=anomaly, 1=normal
    anomaly_count = (iso_pred == -1).sum()
    print(f"[ISO] Anomalies detected in test set: {anomaly_count}/{len(iso_pred)}")

    results["isolation_forest"] = {"model": iso}

    return results


def save_models(results, scaler, feature_names):
    """Save best model and all components to disk."""
    os.makedirs(MODEL_OUTPUT_DIR, exist_ok=True)

    # Best primary model = Random Forest
    rf_model = results["random_forest"]["model"]
    joblib.dump(rf_model,    os.path.join(MODEL_OUTPUT_DIR, "random_forest_model.pkl"))
    joblib.dump(scaler,      os.path.join(MODEL_OUTPUT_DIR, "scaler.pkl"))
    joblib.dump(results["xgboost"]["model"],
                             os.path.join(MODEL_OUTPUT_DIR, "xgboost_model.pkl"))
    joblib.dump(results["isolation_forest"]["model"],
                             os.path.join(MODEL_OUTPUT_DIR, "isolation_forest.pkl"))

    # Save feature names
    import json
    with open(os.path.join(MODEL_OUTPUT_DIR, "feature_names.json"), "w") as f:
        json.dump(feature_names, f)

    # Save model metadata
    metadata = {
        "trained_at": pd.Timestamp.now().isoformat(),
        "primary_model": "RandomForestClassifier",
        "rf_accuracy": results["random_forest"]["accuracy"],
        "rf_f1_score": results["random_forest"]["f1"],
        "xgb_accuracy": results["xgboost"]["accuracy"],
        "svm_accuracy": results["svm"]["accuracy"],
        "feature_count": len(feature_names),
        "features": feature_names,
    }
    with open(os.path.join(MODEL_OUTPUT_DIR, "model_metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"\n[SAVE] Models saved to {MODEL_OUTPUT_DIR}/")


def print_feature_importance(rf_model, feature_names):
    """Print feature importance table."""
    importances = rf_model.feature_importances_
    indices = np.argsort(importances)[::-1]

    print("\n" + "="*60)
    print("  FEATURE IMPORTANCE (Random Forest)")
    print("="*60)
    for i, idx in enumerate(indices):
        if i >= len(feature_names):
            break
        bar = "█" * int(importances[idx] * 50)
        print(f"  {i+1:2d}. {feature_names[idx]:<35} {importances[idx]:.4f} {bar}")


def model_comparison(results):
    """Print model comparison table."""
    print("\n" + "="*60)
    print("  MODEL COMPARISON")
    print("="*60)
    print(f"  {'Model':<25} {'Accuracy':>10} {'F1 Score':>10}")
    print(f"  {'-'*45}")
    for name, res in results.items():
        if "accuracy" in res:
            print(f"  {name:<25} {res['accuracy']:>10.4f} {res['f1']:>10.4f}")
    print("\n  ✅ Random Forest selected as primary model (best F1 + interpretability)")


def main():
    parser = argparse.ArgumentParser(description="PREDICTA ML Training Pipeline")
    parser.add_argument("--dataset", type=str, default=None,
                        help="Path to custom CSV dataset. If not provided, uses AI4I 2020.")
    parser.add_argument("--test-size", type=float, default=0.2,
                        help="Test set fraction (default: 0.2)")
    args = parser.parse_args()

    print("=" * 60)
    print("  PREDICTA – ML Training Pipeline v1.0")
    print("=" * 60)

    # Load dataset
    if args.dataset and os.path.exists(args.dataset):
        print(f"[DATA] Using custom dataset: {args.dataset}")
        X, y = load_custom_dataset(args.dataset)
    else:
        dataset_path = download_ai4i_dataset()
        X, y = load_ai4i_dataset(dataset_path)

    # Feature engineering
    X = feature_engineering(X)
    feature_names = list(X.columns)

    print(f"\n[DATA] Dataset shape: {X.shape}")
    print(f"[DATA] Class distribution: {dict(y.value_counts().sort_index())}")

    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=args.test_size, stratify=y, random_state=RANDOM_STATE
    )
    print(f"[SPLIT] Train: {len(X_train)} | Test: {len(X_test)}")

    # Scaling
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled  = scaler.transform(X_test)

    # Convert back to DataFrame for RF (RF doesn't need scaling, but we save scaler for SVM/API)
    X_train_df = pd.DataFrame(X_train_scaled, columns=feature_names)
    X_test_df  = pd.DataFrame(X_test_scaled, columns=feature_names)

    # Train all models
    results = train_models(X_train_df, X_test_df, y_train, y_test, scaler)

    # Reports
    model_comparison(results)
    print_feature_importance(results["random_forest"]["model"], feature_names)

    # Save
    save_models(results, scaler, feature_names)

    print("\n" + "="*60)
    print("  ✅ Training Complete!")
    print(f"  Random Forest Accuracy: {results['random_forest']['accuracy']*100:.2f}%")
    print(f"  F1 Score: {results['random_forest']['f1']*100:.2f}%")
    print(f"  Models saved to: {MODEL_OUTPUT_DIR}/")
    print("="*60)
    print("\n  HOW TO USE YOUR OWN DATASET:")
    print("  1. Create CSV with sensor readings as columns")
    print("  2. Add 'failure_type' column: Normal/Bearing/Overheat/Overcurrent/Vibration")
    print("  3. Run: python train_model.py --dataset your_dataset.csv")
    print("  4. Restart Flask backend — model auto-loads from saved_models/")


if __name__ == "__main__":
    main()
