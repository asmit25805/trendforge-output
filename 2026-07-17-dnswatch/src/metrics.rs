use anyhow::{Context, Result};
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Instant;

use hyper::service::{make_service_fn, service_fn};
use hyper::{Body, Request, Response, Server};
use log::{error, info};
use prometheus::{
    opts, Encoder, HistogramOpts, HistogramVec, IntCounter, IntGaugeVec, Registry, TextEncoder,
};
use tokio::sync::Mutex;

use crate::app_state::AppState;

/// Collector that aggregates metrics from the shared `AppState`.
pub struct MetricsCollector {
    pub registry: Registry,
    pub latency_histogram: HistogramVec,
    pub success_counter: IntCounter,
    pub dnssec_gauge: IntGaugeVec,
    pub state: Arc<Mutex<AppState>>,
}

impl MetricsCollector {
    /// Create a new collector bound to the given application state.
    pub fn new(state: Arc<Mutex<AppState>>) -> Self {
        let registry = Registry::new();
        let latency_histogram = HistogramVec::new(
            HistogramOpts::new("probe_latency_seconds", "Probe latency in seconds"),
            &["resolver"],
        )
        .expect("failed to create histogram");
        let success_counter = IntCounter::new("probe_success_total", "Total successful probes")
            .expect("failed to create counter");
        let dnssec_gauge = IntGaugeVec::new(
            opts!("dnssec_status", "DNSSEC validation status"),
            &["resolver", "status"],
        )
        .expect("failed to create gauge");

        registry
            .register(Box::new(latency_histogram.clone()))
            .expect("failed to register histogram");
        registry
            .register(Box::new(success_counter.clone()))
            .expect("failed to register counter");
        registry
            .register(Box::new(dnssec_gauge.clone()))
            .expect("failed to register gauge");

        MetricsCollector {
            registry,
            latency_histogram,
            success_counter,
            dnssec_gauge,
            state,
        }
    }

    /// Update the Prometheus metrics from the current application state.
    pub async fn update(&self) -> Result<()> {
        let state = self.state.lock().await;
        for (resolver, metrics) in &state.resolver_metrics {
            let label = resolver.to_string();
            self.latency_histogram
                .with_label_values(&[&label])
                .observe(metrics.avg_latency.as_secs_f64());
            self.success_counter.inc_by(metrics.success_count as u64);
            self.dnssec_gauge
                .with_label_values(&[&label, "secure"])
                .set(metrics.dnssec_secure as i64);
            self.dnssec_gauge
                .with_label_values(&[&label, "bogus"])
                .set(metrics.dnssec_bogus as i64);
        }
        Ok(())
    }
}

/// Run an HTTP server that serves Prometheus metrics.
pub async fn export_prometheus(addr: SocketAddr, collector: Arc<MetricsCollector>) -> Result<()> {
    let make_svc = make_service_fn(move |_| {
        let collector = Arc::clone(&collector);
        async move {
            Ok::<_, hyper::Error>(service_fn(move |_req: Request<Body>| {
                let collector = Arc::clone(&collector);
                async move {
                    collector.update().await.map_err(|e| {
                        error!("failed to update metrics: {}", e);
                        hyper::Error::from(std::io::Error::new(
                            std::io::ErrorKind::Other,
                            "metrics update failed",
                        ))
                    })?;
                    let encoder = TextEncoder::new();
                    let metric_families = collector.registry.gather();
                    let mut buffer = Vec::new();
                    encoder.encode(&metric_families, &mut buffer).unwrap();
                    Ok::<_, hyper::Error>(Response::new(Body::from(buffer)))
                }
            }))
        }
    });

    let server = Server::bind(&addr).serve(make_svc);
    info!("Prometheus exporter listening on {}", addr);
    server.await.context("prometheus server failed")
}
