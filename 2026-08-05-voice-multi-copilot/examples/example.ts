import { Buffer } from 'buffer';
import { AudioGateway } from '../src/gateway/audioGateway';
import { ConversationStream } from '../src/core/conversationStream';
import { CollaborationEngine, AgentRegistry, BaseAgent } from '../src/agents/collaborationEngine';
import { RuntimeConnector } from '../src/backend/runtimeConnector';
import { VoiceSegment, TalkPayload, AgentProfile, TaskTicket } from '../src/types';

// Simple in‑memory agent implementation for demonstration purposes
class EchoAgent implements BaseAgent {
  profile: AgentProfile = {
    id: 'echo-agent',
    name: 'Echo Agent',
    description: 'Repeats back the received speech as text.',
  };

  async handleSegment(segment: VoiceSegment): Promise<NegotiationResult> {
    // Echo the transcript back as a completed task
    const ticket: TaskTicket = {
      id: `task-${Date.now()}`,
      agentId: this.profile.id,
      payload: { text: segment.transcript },
    };
    return { decision: 'accept', ticket };
  }
}

// Initialise core components
const stream = new ConversationStream();
const runtime = new RuntimeConnector('ws://localhost:8080');
const registry = new AgentRegistry();
const engine = new CollaborationEngine(registry, runtime);

// Register a simple agent
registry.registerAgent(new EchoAgent());

// Create and start the audio gateway
const gateway = new AudioGateway(stream, engine);

gateway.start();

console.log('Voice‑multi‑copilot example is running. Press Ctrl+C to stop.');
