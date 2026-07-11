# FlowBridge

**FlowBridge** is a lightweight, event‑driven bridge that streams SaaS actions into real‑time data pipelines. It enables non‑technical users to compose workflows using declarative YAML definitions while developers can extend the platform with provider plugins.

---

## Features

- **Declarative YAML pipelines** – describe complex SaaS orchestrations without writing code.
- **Plugin architecture** – drop a module under `src/providers/` and it becomes instantly available.
- **Credential vault** – encrypted (demo‑only) storage with automatic rotation support.
- **Async execution** – built on `asyncio` for high‑throughput streaming.
- **Run history** – SQLite‑backed persistence for auditability.

---

## Installation

```bash
pip install flowbridge
```

---

## Quick Start

```yaml
# examples/example_pipeline.yaml
id: example_pipeline
description: |
  A minimal pipeline that demonstrates chaining two provider actions.
trigger: manual
nodes:
  - id: create_resource
    provider_id: dummy_provider
    action_id: create
    downstream:
      - notify_user
    params:
      name: "sample"
  - id: notify_user
    provider_id: dummy_provider
    action_id: notify
    downstream: []
    params:
      message: "Resource created"
```

```bash
python -m flowbridge run examples/example_pipeline.yaml
```

---

## Architecture

```
+-------------------+        +-------------------+        +-------------------+
|   YAML Pipeline   |  -->   |  Pipeline Engine  |  -->   |   Provider Plugin |
+-------------------+        +-------------------+        +-------------------+
        |                               |
        v                               v
+-------------------+        +-------------------+
| Credential Vault  |        |   Execution DB    |
+-------------------+        +-------------------+
```

* The **YAML Pipeline** describes a directed‑acyclic graph of actions.
* The **Pipeline Engine** validates the DAG, injects fresh credentials, and
  orchestrates execution using the **Action Executor**.
* **Provider Plugins** implement the concrete logic for each SaaS service.
* The **Credential Vault** stores secrets securely; the **Execution DB** logs
  each action run for traceability.

---

## API Reference

### Core Models (`flowbridge.core.models`)
- `ProviderSpec` – definition of a provider plugin.
- `ActionSpec` – definition of an action a provider can perform.
- `PipelineSpec` – top‑level pipeline description.
- `NodeSpec` – a node in the pipeline DAG.
- `Credential` – stored secret used by providers.
- `RunStatus` – current status of a pipeline run.

### Engine (`flowbridge.core.engine`)
- `PipelineEngine` – class responsible for executing a `PipelineSpec`.
- `run_pipeline(pipeline: PipelineSpec) -> RunStatus` – convenience helper.
- `pipeline_status(pipeline_id: str) -> Optional[RunStatus]` – query latest run.

### Plugin Loader (`flowbridge.plugins.loader`)
- `PluginLoader` – discovers and loads provider plugins from a directory.
- `ProviderPlugin` – protocol that plugins must implement.

### Executor (`flowbridge.execution.executor`)
- `ActionExecutor` – executes a single action with retry logic.
- `execute_action(action, params, credential) -> ActionResult` – helper used by the engine.

### Credential Store (`flowbridge.vault.credential_store`)
- `CredentialVault` – in‑memory vault for storing/retrieving credentials.
- `store_credential(credential) -> str` – store a credential and get its ID.
- `retrieve_credential(cred_id) -> Optional[Credential]` – fetch a credential.

---

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

---

## License

This project is licensed under the MIT License.
