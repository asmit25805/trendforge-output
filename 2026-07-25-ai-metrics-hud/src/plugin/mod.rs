use std::sync::Arc;

use crate::config::loader::Provider;
use crate::core::parser::{TelemetryData, Segment};

/// Trait that a plugin must implement to provide custom segment parsing.
pub trait SegmentProvider: Send + Sync {
    /// Returns the `Provider` this plugin handles.
    fn provider(&self) -> Provider;
    /// Parse raw telemetry into a list of `Segment`s.
    fn parse(&self, data: &TelemetryData) -> Vec<Segment>;
}

/// Registry that holds all compiled‑time providers.
pub struct PluginManager {
    providers: Vec<Arc<dyn SegmentProvider>>,
}

impl PluginManager {
    pub fn new() -> Self {
        Self { providers: Vec::new() }
    }

    pub fn register<P: SegmentProvider + 'static>(&mut self, provider: P) {
        self.providers.push(Arc::new(provider));
    }

    /// Find a provider matching the given name.
    pub fn get(&self, name: &str) -> Option<Arc<dyn SegmentProvider>> {
        for p in &self.providers {
            if p.provider().name == name {
                return Some(p.clone());
            }
        }
        None
    }
}

/// Macro used by downstream crates to register a provider at compile time.
#[macro_export]
macro_rules! register_provider {
    ($manager:expr, $provider:ty) => {
        $manager.register(<$provider>::default());
    };
}
