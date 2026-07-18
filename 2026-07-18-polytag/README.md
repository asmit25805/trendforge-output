# Overview
Polytag is a unified AI‑agent gateway that brings thread‑level large language model (LLM) requests to Slack, Discord, Microsoft Teams, and Mattermost. It enforces policy, supports approvals, shares knowledge across channels, and records immutable audit logs. The system is built in TypeScript and designed for reliability, cost‑awareness, and extensibility.

# Features
- **Multi‑platform support** – One integration point for Slack, Discord, Teams, and Mattermost.  
- **Policy engine** – Centralized compliance checks with optional interactive approvals.  
- **Cost‑aware routing** – Dynamically selects the cheapest runtime that satisfies required capabilities.  
- **Versioned knowledge store** – Append‑only fact store scoped per channel/project for reproducible runs.  
- **Immutable audit logging** – SQLite‑backed run history for compliance and debugging.  
- **Transient‑error handling** – Exponential back‑off retries with deterministic failure messages.  
- **Idempotent execution** – All runs are logged with the original `taskId` to guarantee idempotency.  
- **Extensible adapters** – Plug‑in architecture for additional chat platforms or runtimes.  

# Installation
```bash
npm install polytag
```
All dependencies are declared in `package.json`. The package requires Node 20 or later.

# Quickstart
The following script demonstrates a minimal end‑to‑end flow using the Discord adapter. It creates a mock event, processes it through the gateway, and prints the final response.

```typescript
import { GatewayRouter } from "./src/gateway/router";
import { DiscordAdapter } from "./src/channel/discordAdapter";
import { Engine } from "./src/engine/engine";
import { KnowledgeStore } from "./src/store/knowledgeStore";
import { AuditLogger } from "./src/store/auditLogger";
import { TaskRouter } from "./src/router/taskRouter";
import { RuntimeAdapter } from "./src/runtime/runtimeAdapter";
import { PolicyEngine } from "./src/policy/policyEngine";

// Initialize core components
const knowledgeStore = new KnowledgeStore();
const auditLogger = new AuditLogger();
const runtime = new RuntimeAdapter(); // assumes a simple CLI runtime
const taskRouter = new TaskRouter();
const policyEngine = new PolicyEngine();
const engine = new Engine({
  knowledgeStore,
  auditLogger,
  runtimeAdapter: runtime,
  taskRouter,
  policyEngine,
});

const discordAdapter = new DiscordAdapter({ engine });
const router = new GatewayRouter({
  adapters: [discordAdapter],
  engine,
});

// Simulate an incoming Discord message event
const mockEvent = {
  platform: "discord",
  channelId: "1234567890",
  threadId: null,
  userId: "user-42",
  text: "Summarize the latest project updates.",
  timestamp: Date.now(),
};

(async () => {
  await router.handleEvent(mockEvent);
  console.log("✅ Event processed – check the Discord channel for the reply.");
})();
```

Running the script prints a confirmation line and posts a reply in the mocked Discord channel (the adapter logs the outgoing message to the console). All steps—including policy evaluation, knowledge injection, runtime execution, and audit logging—are exercised.

# Architecture
```
┌────────────────┐
│  GatewayRouter   │
└────────────────┘
        │         
        ▼         
┌────────────────┐
│  ChannelAdapter  │
└────────────────┘
        │         
        ▼         
┌────────────────┐
│  RuntimeAdapter  │
└────────────────┘
        │         
        ▼         
┌────────────────┐
│   PolicyEngine   │
└────────────────┘
        │         
        ▼         
┌────────────────┐
│  KnowledgeStore  │
└────────────────┘
        │         
        ▼         
┌────────────────┐
│   AuditLogger    │
└────────────────┘
        │         
        ▼         
┌────────────────┐
│    TaskRouter    │
└────────────────┘
```

# API Reference

## Types (src/types.ts)

### `EventPayload`
```ts
export interface EventPayload {
  platform: "slack" | "discord" | "teams" | "mattermost";
  channelId: string;
  threadId: string | null;
  userId: string;
  text: string;
  timestamp: number;
}
```
Represents a normalized incoming message from any supported chat platform.

### `TaskDefinition`
```ts
export interface TaskDefinition {
  taskId: string;
  prompt: string;
  requiredCapabilities: string[];
  projectRef: ProjectRef;
  knowledgeVersion: number;
}
```
Describes a unit of work to be executed by a runtime.

### `KnowledgeEntry`
```ts
export interface KnowledgeEntry {
  id: string;
  projectId: string;
  channelId: string;
  version: number;
  fact: string;
  authorId: string;
  createdAt: number;
}
```
Immutable fact stored in the KnowledgeStore.

### `AuditRecord`
```ts
export interface AuditRecord {
  runId: string;
  runtimeId: string;
  startTime: number;
  endTime: number;
  status: "success" | "error" | "cancelled";
  output: string | null;
  errorMessage: string | null;
  approvalId: string | null;
}
```
Log entry persisted by AuditLogger.

### `PolicyDecision`
```ts
export interface PolicyDecision {
  allow: boolean;
  requiresApproval: boolean;
  reason: string;
}
```
Result of a policy evaluation.

### `ProjectRef`
```ts
export interface ProjectRef {
  repoUrl: string;
  branch: string;
}
```
Reference to a code repository used by a task.

### `ApprovalPayload`
```ts
export interface ApprovalPayload {
  taskId: string;
  requesterId: string;
  details: string;
}
```
Payload sent to a platform when user approval is required.

## Classes

### `GatewayRouter` (src/gateway/router.ts)
```ts
export class GatewayRouter {
  constructor(options: { adapters: ChannelAdapter[]; engine: Engine });

  /**
   * Validates, deduplicates, and routes the incoming event to the appropriate channel adapter.
   */
  handleEvent(event: EventPayload): Promise<void>;

  /**
   * Emits an interactive approval request on the originating platform.
   */
  emitApprovalRequest(taskId: string, details: ApprovalPayload): void;
}
```

### `ChannelAdapter` (src/channel/discordAdapter.ts)
```ts
export abstract class ChannelAdapter {
  /**
   * Extracts thread, user, and channel identifiers from a raw webhook payload.
   */
  abstract parseIncoming(raw: any): EventPayload;

  /**
   * Posts a reply or interactive card back to the platform.
   */
  abstract sendMessage(target: TargetRef, content: MessageContent): Promise<void>;
}
```

### `DiscordAdapter` (src/channel/discordAdapter.ts)
```ts
export class DiscordAdapter extends ChannelAdapter {
  constructor(options: { engine: Engine });

  parseIncoming(raw: any): EventPayload;
  sendMessage(target: TargetRef, content: MessageContent): Promise<void>;
}
```

### `RuntimeAdapter` (src/runtime/runtimeAdapter.ts)
```ts
export class RuntimeAdapter {
  /**
   * Spawns the process, streams output, and enforces timeout/capabilities.
   */
  execute(task: TaskDefinition, context: ExecutionContext): Promise<RuntimeResult>;

  /**
   * Indicates whether this runtime supports a given capability.
   */
  supportsCapability(cap: string): boolean;
}
```

### `PolicyEngine` (src/policy/policyEngine.ts)
```ts
export class PolicyEngine {
  /**
   * Returns allow/deny or approval‑required decision for a task.
   */
  evaluate(task: TaskDefinition, context: ExecutionContext): PolicyDecision;

  /**
   * Dynamically injects a new compliance rule.
   */
  registerRule(rule: PolicyRule): void;
}
```

### `KnowledgeStore` (src/store/knowledgeStore.ts)
```ts
export class KnowledgeStore {
  /**
   * Returns the latest facts for a channel/project.
   */
  getFacts(ref: KnowledgeRef): Promise<KnowledgeEntry[]>;

  /**
   * Adds a new immutable fact with version bump.
   */
  appendFact(entry: KnowledgeEntry): Promise<void>;

  /**
   * Retrieves a snapshot of facts for reproducible runs.
   */
  snapshot(ref: KnowledgeRef, version: number): Promise<KnowledgeEntry[]>;
}
```

### `AuditLogger` (src/store/auditLogger.ts)
```ts
export class AuditLogger {
  /**
   * Persists a complete run trace.
   */
  logRun(record: AuditRecord): Promise<void>;

  /**
   * Retrieves run records for admin UI.
   */
  queryRuns(filter: AuditFilter): Promise<AuditRecord[]>;
}
```

### `TaskRouter` (src/router/taskRouter.ts)
```ts
export class TaskRouter {
  /**
   * Applies fallback ordering and cost heuristics to select a runtime.
   */
  selectRuntime(task: TaskDefinition, candidates: RuntimeAdapter[]): RuntimeAdapter;

  /**
   * Ensures read‑only runtimes are tried before write‑capable ones.
   */
  fallbackToReadOnly(task: TaskDefinition): RuntimeAdapter;
}
```

### `Engine` (src/engine/engine.ts)
```ts
export class Engine {
  constructor(options: {
    knowledgeStore: KnowledgeStore;
    auditLogger: AuditLogger;
    runtimeAdapter: RuntimeAdapter;
    taskRouter: TaskRouter;
    policyEngine: PolicyEngine;
  });

  /**
   * Orchestrates the full lifecycle: policy, approval, runtime execution, and logging.
   */
  runTask(event: EventPayload): Promise<void>;
}
```

# Contributing
We welcome contributions from the community.

1. **Fork** the repository at `github.com/asmit25805/polytag`.
2. **Create** a new branch for your feature or bug fix.
3. **Write** tests under the `test/` directory. Each test file must contain at least six test functions that assert real behavior.
4. **Run** the full test suite with `npm test`. All tests must pass.
5. **Submit** a pull request targeting the `main` branch. The CI workflow will automatically lint, test, and verify your changes.

Please ensure that new code follows the existing coding style, includes comprehensive TypeScript type annotations, and updates the README API reference when public interfaces change.

# Additional Resources
- **GitHub repository**: https://github.com/asmit25805/polytag  
- **Issue tracker**: Use the GitHub Issues page to report bugs or request features.  
- **Discussion**: Join the project’s Discussions tab for design debates and usage questions.  

# Release Process
Releases are cut from the `main` branch after CI passes and a changelog entry is added. The version is bumped according to semantic versioning. Deployments to npm are performed automatically via GitHub Actions.