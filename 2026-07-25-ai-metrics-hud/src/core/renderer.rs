use std::io::{self, Write};
use std::thread::sleep;
use std::time::Duration;

use colored::{Color, Colorize};
use log::{debug, error};

use crate::config::loader::{Config, Provider, SegmentConfig, Severity, ThemeConfig};
use crate::core::parser::Segment;

/// Collects segments according to configuration.
pub struct SegmentCollector<'a> {
    config: &'a Config,
    collected: Vec<Segment>,
}

impl<'a> SegmentCollector<'a> {
    pub fn new(config: &'a Config) -> Self {
        Self { config, collected: Vec::new() }
    }

    /// Filter and store segments based on the configuration.
    pub fn collect(&mut self, segments: Vec<Segment>) {
        for seg in segments {
            // Find matching segment config if any.
            if let Some(sc) = self.config.segments.iter().find(|c| c.key == seg.key) {
                if !sc.enabled { continue; }
                if seg.severity as u8 >= Severity::Info as u8 { // simplistic filter
                    self.collected.push(seg);
                }
            } else {
                // If no explicit config, keep the segment.
                self.collected.push(seg);
            }
        }
        // Sort according to order defined in SegmentConfig.
        self.collected.sort_by_key(|s| {
            self.config.segments.iter().find(|c| c.key == s.key).map_or(usize::MAX, |c| c.order)
        });
    }

    pub fn segments(&self) -> &[Segment] {
        &self.collected
    }
}

/// Renders the final status line to stdout.
pub struct StatusLineRenderer<'a> {
    config: &'a Config,
}

impl<'a> StatusLineRenderer<'a> {
    pub fn new(config: &'a Config) -> Self {
        Self { config }
    }

    /// Render the provided segments respecting the theme.
    pub fn render(&mut self, segments: &[Segment]) -> io::Result<()> {
        let mut out = String::new();
        for seg in segments {
            let coloured = match seg.severity {
                Severity::Error => seg.value.red(),
                Severity::Warning => seg.value.yellow(),
                Severity::Info => seg.value.green(),
                Severity::Debug => seg.value.blue(),
            };
            out.push_str(&format!("{}:{} ", seg.key, coloured));
        }
        // Write with retry logic.
        const MAX_RETRIES: usize = 3;
        for attempt in 0..MAX_RETRIES {
            match io::stdout().write_all(out.as_bytes()) {
                Ok(_) => return Ok(()),
                Err(e) if attempt + 1 == MAX_RETRIES => return Err(e),
                Err(_) => {
                    sleep(Duration::from_millis(10 * 2_u64.pow(attempt as u32)));
                }
            }
        }
        Ok(())
    }
}
