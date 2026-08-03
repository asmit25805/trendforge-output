# Overview
Tracecraft captures developer sessions—including terminal commands, file system changes, and network activity—and transforms them into portable CI/CD pipelines using AI‑generated scripts.  
It is designed for reproducible builds, automated testing, and seamless integration with modern DevOps workflows.  

# Features
- **Multi‑source recording** – Collects command line input, file modifications, and HTTP traffic in a single session.  
- **Chronological event aggregation** – Preserves exact ordering across all collectors for faithful replay.  
- **AI‑assisted pipeline generation** – Sends recorded sessions to a configurable LLM to obtain a high‑level intent and a concrete `PipelineSpec`.  
- **Template‑driven rendering** – Uses Tera templates to produce GitHub Actions workflows, Dockerfiles, and shell scripts.  
- **Dry‑run validation** – Executes a sandboxed lint step to guarantee syntactic correctness before artifacts are stored.  
- **Bounded LRU cache** – Reuses identical LLM responses, reducing API costs and latency.  
- **Robust error handling** – Fatal errors abort with clear messages; transient failures are retried with exponential back‑off.  
- **Colored CLI feedback** – Red for fatal, yellow for retryable, green for successful operations.  

# Installation
```bash
# Add tracecraft to your Cargo.toml
cargo add tracecraft

# Verify the binary is available
tracecraft --version
```
The binary will be installed to `~/.cargo/bin`. Ensure this directory is in your `PATH`.  

# Quickstart
The following example demonstrates a complete workflow from recording a session to generating pipeline artifacts.

```bash
# 1. Start a recording session
$ tracecraft record --config examples/basic_usage.rs
[INFO] Starting session 3f9c2a1e-5b4d-4a9e-8f2c-1d2e3f4a5b6c
[INFO] Enabled collectors: command, filesystem, network
[INFO] Recording... Press Ctrl‑C to stop.

# (User works in the terminal, edits files, makes HTTP requests)

# 2. Stop the session (Ctrl‑C)
[INFO] Stopping collectors
[INFO] Session saved to /home/user/.tracecraft/sessions/3f9c2a1e-5b4d-4a9e-8f2c-1d2e3f4a5b6c.json
[INFO] Sending bundle to LLM
[INFO] Received pipeline spec (intent: "Build and test a Rust project")
[INFO] Rendering artifacts
[INFO] Dry‑run validation succeeded
[INFO] Artifacts stored at /home/user/.tracecraft/artifacts/3f9c2a1e-5b4d-4a9e-8f2c-1d2e3f4a5b6c/
[INFO] Run `cat /home/user/.tracecraft/artifacts/3f9c2a1e-5b4d-4a9e-8f2c-1d2e3f4a5b6c/run.sh` to view the entry script.
```

The generated `run.sh` script can be executed locally or committed to a repository. The accompanying GitHub Actions workflow (`.github/workflows/trace.yml`) will trigger according to the specified `TriggerSpec`.  

# Architecture
```
┌─────────────────┐
│  SessionRecorder  │
└─────────────────┘
         │         
         ▼         
┌─────────────────┐
│  EventCollector   │
└─────────────────┘
         │         
         ▼         
┌─────────────────┐
│  LLMTransformer   │
└─────────────────┘
         │         
         ▼         
┌─────────────────┐
│  PipelineBuilder  │
└─────────────────┘
         │         
         ▼         
┌─────────────────┐
│   ResourceCache   │
└─────────────────┘
```  

The diagram illustrates the data flow: `SessionRecorder` orchestrates collectors, streams events to `LLMTransformer`, which produces a `PipelineSpec`. `PipelineBuilder` renders artifacts, and `ResourceCache` stores reusable specifications.  

# API Reference
## SessionRecorder
```rust
pub struct SessionRecorder {
    /// Starts the recording session with the given configuration.
    pub fn start(&mut self, config: RecorderConfig) -> Result<(), RecorderError>;

    /// Stops all collectors, flushes buffers, and returns the completed bundle.
    pub fn stop(&mut self) -> Result<SessionBundle, RecorderError>;

    /// Registers a new collector for the current session.
    pub fn add_collector(&mut self, collector: Box<dyn EventCollector>);
}
```
- `RecorderConfig` defines which collectors are enabled and their individual settings.  
- `RecorderError` enumerates fatal errors such as collector spawn failures.  

## EventCollector (trait)
```rust
pub trait EventCollector: Send + Sync {
    /// Begins polling or subscribing to the source.
    fn start(&mut self) -> Result<(), CollectorError>;

    /// Releases resources associated with the collector.
    fn stop(&mut self) -> Result<(), CollectorError>;

    /// Returns the next captured event or `None` if no new data.
    fn poll(&mut self) -> Option<Event>;
}
```
Implemented by `CommandCollector`, `FilesystemCollector`, and `NetworkCollector`.  

## LLMTransformer
```rust
pub struct LLMTransformer {
    /// Sends the bundle to the LLM and parses the response into a PipelineSpec.
    pub fn transform(
        &self,
        bundle: &SessionBundle,
        feedback: Option<String>,
    ) -> Result<PipelineSpec, LLMError>;

    /// Returns the retry policy for transient API failures.
    pub fn retry_policy(&self) -> RetryPolicy;
}
```
- `LLMError` covers authentication failures and malformed responses.  
- `RetryPolicy` defines exponential back‑off parameters.  

## PipelineBuilder
```rust
pub struct PipelineBuilder {
    /// Renders files from a PipelineSpec and runs a dry‑run lint step.
    pub fn build(&self, spec: &PipelineSpec) -> Result<PipelineArtifacts, BuildError>;

    /// Validates generated artifacts against schema and syntax rules.
    pub fn validate(&self, artifacts: &PipelineArtifacts) -> Result<(), ValidationError>;
}
```
- `PipelineArtifacts` contains paths to generated files.  

## ResourceCache
```rust
pub struct ResourceCache {
    /// Retrieves a cached spec by its hash, if present.
    pub fn get(&self, hash: &str) -> Option<PipelineSpec>;

    /// Inserts a new spec, evicting the oldest entry when capacity exceeds MAX_CACHE.
    pub fn insert(&mut self, hash: String, spec: PipelineSpec);
}
```
- Cache capacity is bounded to eight entries (`MAX_CACHE = 8`).  

## Data Models
### SessionBundle
```rust
pub struct SessionBundle {
    pub id: Uuid,
    pub started_at: DateTime<Utc>,
    pub events: Vec<Event>,
    pub metadata: SessionMetadata,
}
```
### CommandEvent
```rust
pub struct CommandEvent {
    pub timestamp: DateTime<Utc>,
    pub command: String,
    pub exit_code: i32,
    pub stdout_hash: String,
    pub stderr_hash: String,
}
```
### FileChangeEvent
```rust
pub struct FileChangeEvent {
    pub timestamp: DateTime<Utc>,
    pub path: PathBuf,
    pub change_type: ChangeType,
    pub content_hash: Option<String>,
}
```
### NetworkEvent
```rust
pub struct NetworkEvent {
    pub timestamp: DateTime<Utc>,
    pub method: String,
    pub url: String,
    pub status: u16,
    pub request_body_hash: Option<String>,
    pub response_body_hash: Option<String>,
}
```
### PipelineSpec
```rust
pub struct PipelineSpec {
    pub intent: String,
    pub steps: Vec<PipelineStep>,
    pub trigger: TriggerSpec,
}
```
### PipelineStep
```rust
pub struct PipelineStep {
    pub id: String,
    pub action: String,
    pub tool: Tool,
    pub script: String,
}
```
### TriggerSpec
```rust
pub struct TriggerSpec {
    pub type_: TriggerType,
    pub cron: Option<String>,
    pub branch: Option<String>,
}
```
All models implement `serde::Serialize` and `serde::Deserialize` for JSON persistence.  

# Contributing
1. **Fork** the repository at `github.com/asmit25805/tracecraft`.  
2. **Create** a new branch for your feature or bug fix.  
3. **Run** the test suite locally:  
   ```bash
   cargo test
   ```  
4. **Ensure** code passes `cargo clippy` and is formatted with `cargo fmt`.  
5. **Submit** a pull request targeting the `main` branch.  
   - Include a description of the change and reference any related issues.  
   - The CI workflow will automatically run linting and tests.  

All contributions must adhere to the project's coding standards: use async/await, provide comprehensive error handling, and include documentation for any new public API.  

# Additional Resources
- **Documentation** – Generated API docs are available via `cargo doc --open`.  
- **Issue Tracker** – Report bugs or request features at `github.com/asmit25805/tracecraft/issues`.  
- **Community** – Discussions happen in the repository's Discussions tab.  

# Release History
- **v0.1.0** – Initial implementation of recording, LLM transformation, and pipeline building.  
- **v0.2.0** – Added bounded LRU cache and improved dry‑run validation.  
- **v0.3.0** – Introduced network collector and enhanced error retry policies.  

# Acknowledgments
Thanks to the open‑source Rust ecosystem for providing crates such as `tokio`, `serde`, `uuid`, and `tera`, which make Tracecraft possible.