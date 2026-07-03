from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from typing import List, Optional, Callable, Deque, Any, Dict

import requests
from influxdb_client import InfluxDBClient, Point, WritePrecision
from paho.mqtt import client as mqtt_client

from src.core.models import MachineTelemetry

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #


def _exponential_backoff(attempt: int, base: float = 0.5, cap: float = 8.0) -> float:
    """Calculate a back‑off delay for ``attempt`` (0‑based)."""
    return min(cap, base * (2 ** attempt))


# --------------------------------------------------------------------------- #
# DataIngestor implementation
# --------------------------------------------------------------------------- #


class DataIngestor:
    """
    Collects real‑time telemetry from coffee machines via MQTT or HTTP and stores
    raw records in InfluxDB with resilient retry logic.
    """

    def __init__(
        self,
        influx_url: str,
        influx_token: str,
        influx_org: str,
        influx_bucket: str,
        max_retries: int = 5,
    ) -> None:
        """
        Initialise the ingestor and the InfluxDB client.

        Args:
            influx_url: URL of the InfluxDB instance.
            influx_token: Authentication token.
            influx_org: Organisation name in InfluxDB.
            influx_bucket: Bucket where telemetry will be written.
            max_retries: Maximum retry attempts for network operations.
        """
        self._influx_client = InfluxDBClient(
            url=influx_url, token=influx_token, org=influx_org
        )
        self._bucket = influx_bucket
        self._max_retries = max_retries

        # MQTT/HTTP configuration
        self._mqtt_client: Optional[mqtt_client.Client] = None
        self._http_endpoint: Optional[str] = None

        # Internal queue for MQTT messages (thread‑safe)
        self._msg_queue: Deque[MachineTelemetry] = deque()
        self._queue_lock = threading.Lock()
        self._mqtt_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # --------------------------------------------------------------------- #
    # Connection handling
    # --------------------------------------------------------------------- #

    def connect(self, endpoint: str) -> None:
        """
        Establish a resilient connection to the telemetry source.

        The function supports ``mqtt://`` and ``http://``/``https://`` schemes.
        """
        if endpoint.startswith("mqtt://"):
            self._setup_mqtt(endpoint.removeprefix("mqtt://"))
        elif endpoint.startswith(("http://", "https://")):
            self._http_endpoint = endpoint
            logger.info("Configured HTTP telemetry source: %s", endpoint)
        else:
            raise ValueError(
                f"Unsupported endpoint scheme in '{endpoint}'. Use mqtt:// or http(s)://"
            )

    def _setup_mqtt(self, broker_url: str) -> None:
        """
        Initialise an MQTT client, start a background thread and subscribe to
        the ``telemetry`` topic.
        """
        host, _, port_str = broker_url.partition(":")
        port = int(port_str) if port_str else 1883

        client_id = f"brew-ops-{int(time.time())}"
        client = mqtt_client.Client(client_id=client_id)

        client.on_connect = self._on_mqtt_connect
        client.on_message = self._on_mqtt_message
        client.on_disconnect = self._on_mqtt_disconnect

        # Connection with retry/back‑off
        for attempt in range(self._max_retries):
            try:
                client.connect(host, port, keepalive=60)
                break
            except Exception as exc:
                logger.warning(
                    "MQTT connection attempt %d failed: %s", attempt + 1, exc
                )
                if attempt == self._max_retries - 1:
                    raise
                time.sleep(_exponential_backoff(attempt))

        self._mqtt_client = client
        self._mqtt_thread = threading.Thread(
            target=self._mqtt_loop, daemon=True, name="mqtt-loop"
        )
        self._mqtt_thread.start()
        logger.info("MQTT client started and listening on %s:%s", host, port)

    def _mqtt_loop(self) -> None:
        """Run the MQTT network loop until stopped."""
        assert self._mqtt_client is not None
        while not self._stop_event.is_set():
            self._mqtt_client.loop(timeout=1.0)

    def _on_mqtt_connect(self, client: mqtt_client.Client, userdata: Any, flags: Any, rc: int) -> None:
        """Subscribe to the telemetry topic after a successful connection."""
        if rc == 0:
            client.subscribe("telemetry")
            logger.info("Subscribed to MQTT topic 'telemetry'")
        else:
            logger.error("Failed to connect to MQTT broker, rc=%s", rc)

    def _on_mqtt_message(self, client: mqtt_client.Client, userdata: Any, msg: mqtt_client.MQTTMessage) -> None:
        """Parse incoming MQTT payloads into ``MachineTelemetry`` objects."""
        try:
            payload = json.loads(msg.payload.decode())
            telemetry = MachineTelemetry(**payload)
            with self._queue_lock:
                self._msg_queue.append(telemetry)
        except Exception as exc:
            logger.exception("Failed to parse MQTT message: %s", exc)

    def _on_mqtt_disconnect(self, client: mqtt_client.Client, userdata: Any, rc: int) -> None:
        """Log disconnections; the client will attempt reconnection automatically."""
        logger.warning("MQTT client disconnected with rc=%s", rc)

    # --------------------------------------------------------------------- #
    # Data retrieval
    # --------------------------------------------------------------------- #

    def fetch_batch(self, limit: int = 1000) -> List[MachineTelemetry]:
        """
        Pull the latest batch of raw data from the configured source.

        For MQTT, the method drains up to ``limit`` items from the internal queue.
        For HTTP, a GET request is performed with ``?limit=`` query parameter.
        """
        if self._mqtt_client:
            return self._drain_queue(limit)
        if self._http_endpoint:
            return self._fetch_http(limit)
        raise RuntimeError("DataIngestor is not connected to any source")

    def _drain_queue(self, limit: int) -> List[MachineTelemetry]:
        """Extract up to ``limit`` telemetry records from the MQTT queue."""
        records: List[MachineTelemetry] = []
        with self._queue_lock:
            while self._msg_queue and len(records) < limit:
                records.append(self._msg_queue.popleft())
        logger.debug("Fetched %d records from MQTT queue", len(records))
        return records

    def _fetch_http(self, limit: int) -> List[MachineTelemetry]:
        """Perform a simple HTTP GET to retrieve telemetry."""
        url = f"{self._http_endpoint}?limit={limit}"
        for attempt in range(self._max_retries):
            try:
                resp = requests.get(url, timeout=5)
                resp.raise_for_status()
                raw_list = resp.json()
                return [MachineTelemetry(**item) for item in raw_list]
            except requests.RequestException as exc:
                logger.warning(
                    "HTTP fetch attempt %d failed for %s: %s", attempt + 1, url, exc
                )
                if attempt == self._max_retries - 1:
                    raise
                time.sleep(_exponential_backoff(attempt))

    # --------------------------------------------------------------------- #
    # Persistence
    # --------------------------------------------------------------------- #

    def store(self, records: List[MachineTelemetry]) -> None:
        """
        Write raw telemetry to InfluxDB with exponential back‑off retry logic.

        If all attempts fail, a sentinel metric ``ingest_failure`` is emitted
        for alerting purposes.
        """
        if not records:
            logger.info("No telemetry records to store")
            return

        points = [
            Point("machine_telemetry")
            .tag("machine_id", rec.machine_id)
            .field("temperature_c", rec.temperature_c)
            .field("pressure_bar", rec.pressure_bar)
            .field("flow_rate_ml_s", rec.flow_rate_ml_s)
            .field("error_code", rec.error_code if rec.error_code is not None else 0)
            .time(rec.timestamp, WritePrecision.NS)
            for rec in records
        ]

        write_api = self._influx_client.write_api()
        for attempt in range(self._max_retries):
            try:
                write_api.write(bucket=self._bucket, record=points)
                logger.info("Successfully stored %d telemetry points", len(points))
                return
            except Exception as exc:
                logger.warning(
                    "InfluxDB write attempt %d failed: %s", attempt + 1, exc
                )
                if attempt == self._max_retries - 1:
                    self._emit_sentinel_metric()
                    raise
                time.sleep(_exponential_backoff(attempt))

    def _emit_sentinel_metric(self) -> None:
        """Emit a minimal metric indicating a persistent ingest failure."""
        point = (
            Point("ingest_failure")
            .field("failed", 1)
            .time(_dt.datetime.utcnow(), WritePrecision.NS)
        )
        try:
            self._influx_client.write_api().write(bucket=self._bucket, record=point)
            logger.info("Sentinel metric 'ingest_failure' emitted")
        except Exception as exc:
            logger.error("Failed to emit sentinel metric: %s", exc)

    # --------------------------------------------------------------------- #
    # Graceful shutdown
    # --------------------------------------------------------------------- #

    def close(self) -> None:
        """Terminate background threads and close network resources."""
        self._stop_event.set()
        if self._mqtt_client:
            self._mqtt_client.disconnect()
        self._influx_client.close()
        logger.info("DataIngestor shutdown complete")