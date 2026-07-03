# Brew Ops Dashboard

Brew Ops Dashboard is an open‑source Python project that predicts coffee‑machine failures before they happen. By ingesting real‑time telemetry from espresso machines, cleaning and enriching the data, scoring failure risk, and turning high‑risk scores into concrete maintenance tasks, the system keeps cafés running smoothly. A lightweight Streamlit UI presents live health dashboards and actionable tickets to baristas.

## Features

- **Real‑time ingestion** – MQTT and HTTP collectors store raw telemetry in InfluxDB.
- **Robust processing** – Outlier removal, missing‑value imputation, and feature engineering for time‑series models.
- **Hybrid prediction** – Prophet captures trend/seasonality while XGBoost detects anomalies.
- **Maintenance recommendation** – Risk thresholds are translated into concrete maintenance tickets.

## Installation

```bash
pip install brew-ops-dashboard
```

## Quick Start

```bash
python -m brew_ops_dashboard.examples.run_demo
```

## Architecture

![Architecture Diagram](docs/architecture.png)

The system consists of three main layers:

1. **Ingestion** – `DataIngestor` collects telemetry via MQTT/HTTP and writes to InfluxDB.
2. **Processing** – `TelemetryProcessor` cleans and prepares data for modeling.
3. **Prediction & Recommendation** – `FailurePredictor` scores risk; `MaintenanceRecommender` creates tasks.

## API Reference

### Core Models

- `MachineTelemetry` – Raw telemetry record.
- `FailurePrediction` – Predicted failure probability and timestamp.
- `MaintenanceTask` – Recommended maintenance action.

### Core Engine

- `FailurePredictor` – Provides `predict(df: pd.DataFrame) -> FailurePrediction`.
- `MaintenanceRecommender` – Provides `recommend(prediction: FailurePrediction) -> MaintenanceTask`.

### Ingestion

- `DataIngestor` – Starts MQTT/HTTP listeners and stores data.

### UI

- `StreamlitApp` – Launches the dashboard UI.

## Contributing

Contributions are welcome! Please open issues or pull requests.
