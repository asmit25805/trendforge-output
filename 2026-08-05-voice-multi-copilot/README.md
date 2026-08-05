# voice‑multi‑copilot

## Overview
voice‑multi‑copilot is a real‑time, multi‑agent voice co‑pilot that lets several AI assistants share a single audio channel. User speech is captured, segmented, and dispatched to a dynamic pool of agents. Agents propose tasks, negotiate, and execute tool calls through a backend runtime. All interactions are persisted in a conversation stream that can be replayed or used for context by new agents.

The system is built in TypeScript, runs in Node.js, and communicates with a backend over a JSON‑RPC WebSocket. It is designed for low latency, deterministic negotiation, and graceful error handling.

## Features
- **Shared AudioGateway** – single VAD pipeline, minimal echo, consistent voice detection.
- **Dynamic AgentRegistry** – load, unload, and prioritize agents at runtime.
- **Negotiation Engine** – deterministic task negotiation among agents.
- **Conversation Stream** – immutable snapshots of the dialogue for replay and context.
- **Runtime Connector** – JSON‑RPC WebSocket bridge to execute tool calls.

## Installation
```bash
npm install voice-multi-copilot
```

## Quick Start
```ts
import { AudioGateway } from "voice-multi-copilot/src/gateway/audioGateway";
import { ConversationStream } from "voice-multi-copilot/src/core/conversationStream";
import { CollaborationEngine, AgentRegistry } from "voice-multi-copilot/src/agents/collaborationEngine";
import { RuntimeConnector } from "voice-multi-copilot/src/backend/runtimeConnector";

// Initialise core components
const stream = new ConversationStream();
const runtime = new RuntimeConnector("ws://localhost:8080");
const registry = new AgentRegistry();
const engine = new CollaborationEngine(registry, runtime);
const gateway = new AudioGateway(stream, engine);

gateway.start();
```

## API Reference
### AudioGateway
- **constructor(stream: ConversationStream, engine: CollaborationEngine)** – Creates a new gateway.
- **start(): void** – Begins capturing audio and processing voice segments.
- **stop(): void** – Stops the audio capture.

### VADProcessor
- **process(buffer: Buffer): VoiceSegment[]** – Performs voice activity detection on raw audio data.

### CollaborationEngine
- **registerAgent(agent: BaseAgent): void** – Adds an agent to the pool.
- **unregisterAgent(agentId: string): void** – Removes an agent.
- **negotiate(segment: VoiceSegment): Promise<NegotiationResult>** – Runs the negotiation cycle for a voice segment.

### ConversationStream
- **appendSegment(segment: VoiceSegment): void** – Adds a new segment to the stream.
- **snapshot(): ConversationSnapshot** – Returns an immutable snapshot of the current conversation.

### RuntimeConnector
- **sendTask(ticket: TaskTicket): Promise<RuntimeResponse>** – Sends a task to the backend runtime and awaits the result.

## Architecture
```
+-------------------+      +-------------------+      +-------------------+
|   AudioGateway   | ---> | CollaborationEngine| ---> | RuntimeConnector |
+-------------------+      +-------------------+      +-------------------+
          |                         |                         |
          v                         v                         v
+-------------------+      +-------------------+      +-------------------+
| ConversationStream|      |   AgentRegistry   |      |   Backend Server  |
+-------------------+      +-------------------+      +-------------------+
```

- **AudioGateway** captures raw audio, runs VAD, and forwards voice segments to the **CollaborationEngine**.
- **CollaborationEngine** uses the **AgentRegistry** to dispatch segments to agents, runs negotiation, and creates **TaskTicket** objects.
- **RuntimeConnector** sends the tickets to the backend server, receives **RuntimeResponse**, and feeds results back into the conversation stream.
- **ConversationStream** stores immutable snapshots for replay or context sharing.

## Contributing
Contributions are welcome! Please open issues or submit pull requests.
