import { EventEmitter } from 'eventemitter3';
import { Buffer } from 'buffer';
import { AudioGateway } from '../src/gateway/audioGateway';
import {
  AgentRegistry,
  BaseAgent,
  CollaborationEngine,
} from '../src/agents/collaborationEngine';
import {
  VoiceSegment,
  TalkPayload,
  AgentProfile,
  TaskTicket,
} from '../src/types';

// Helper: simple in‑memory agent that records received segments
class RecordingAgent implements BaseAgent {
  profile: AgentProfile;
  received: VoiceSegment[] = [];

  constructor(id: string, capabilities: string[] = []) {
    this.profile = {
      id,
      name: `Agent ${id}`,
      capabilities,
      priority: 0,
      state: 'idle',
    };
  }

  async handleProposal(_: TaskTicket): Promise<boolean> {
    return true;
  }

  async onVoiceSegment(segment: VoiceSegment): Promise<void> {
    this.received.push(segment);
  }
}

// Mock WebSocket to avoid real network traffic
jest.mock('ws', () => {
  return jest.fn().mockImplementation(() => {
    const ws = new EventEmitter();
    ws.readyState = 1; // OPEN
    ws.send = jest.fn();
    ws.close = jest.fn();
    return ws;
  });
});

describe('AudioGateway integration tests', () => {
  let gateway: AudioGateway;
  let registry: AgentRegistry;
  let engine: CollaborationEngine;
  let agentA: RecordingAgent;
  let agentB: RecordingAgent;

  beforeEach(async () => {
    registry = new AgentRegistry();
    engine = new CollaborationEngine(registry);
    gateway = new AudioGateway(registry, engine);
    agentA = new RecordingAgent('a', ['echo']);
    agentB = new RecordingAgent('b', ['translate']);
    registry.register(agentA);
    registry.register(agentB);
    await gateway.start();
  });

  afterEach(() => {
    jest.clearAllMocks();
    gateway.removeAllListeners();
  });

  test('start resolves without throwing', async () => {
    await expect(gateway.start()).resolves.toBeUndefined();
  });

  test('dispatchSegment routes segment to all registered agents', () => {
    const segment: VoiceSegment = {
      audio: Buffer.from([0x01, 0x02]),
      timestamp: Date.now(),
      speakerId: null,
      intent: null,
      vadScore: 0.9,
    };
    gateway.dispatchSegment(segment);
    expect(agentA.received).toContainEqual(segment);
    expect(agentB.received).toContainEqual(segment);
  });

  test('dispatchSegment respects intent‑based selection', () => {
    // Override selectAgents to filter by capability
    jest.spyOn(registry, 'selectAgents').mockImplementation((intent: string) => {
      if (intent === 'echo') return [agentA];
      return [];
    });

    const segment: VoiceSegment = {
      audio: Buffer.from([0x03]),
      timestamp: Date.now(),
      speakerId: null,
      intent: 'echo',
      vadScore: 0.95,
    };
    gateway.dispatchSegment(segment);
    expect(agentA.received).toContainEqual(segment);
    expect(agentB.received).toHaveLength(0);
  });

  test('mixAndPlay emits talk event with correct payload', (done) => {
    const talk: TalkPayload = {
      audio: Buffer.from([0x0a]),
      text: 'Test speech',
    };
    gateway.on('talk', (payload: TalkPayload) => {
      try {
        expect(payload).toEqual(talk);
        done();
      } catch (e) {
        done(e);
      }
    });
    gateway.mixAndPlay(talk);
  });

  test('transient VAD error triggers retry logic up to three attempts', async () => {
    // Simulate a VAD processor that throws on first two calls
    const originalProcess = (gateway as any).processAudioChunk;
    const mockProcess = jest
      .fn()
      .mockImplementationOnce(() => {
        throw new Error('VAD transient error');
      })
      .mockImplementationOnce(() => {
        throw new Error('VAD transient error');
      })
      .mockImplementation(() => {
        // Successful processing returns a VoiceSegment
        return {
          audio: Buffer.from([0x05]),
          timestamp: Date.now(),
          speakerId: null,
          intent: null,
          vadScore: 0.8,
        };
      });
    (gateway as any).processAudioChunk = mockProcess;

    const segment = await (gateway as any).captureAndProcess(); // method that triggers VAD flow
    expect(mockProcess).toHaveBeenCalledTimes(3);
    expect(segment).toMatchObject({
      audio: expect.any(Buffer),
      vadScore: expect.any(Number),
    });

    // Restore original implementation
    (gateway as any).processAudioChunk = originalProcess;
  });

  test('fatal microphone error emits error event and shuts down gracefully', (done) => {
    // Simulate fatal error during start
    jest.spyOn(gateway as any, 'initializeMicrophone').mockImplementation(() => {
      throw new Error('Microphone not found');
    });

    gateway.once('error', (err: Error) => {
      try {
        expect(err.message).toMatch(/Microphone not found/);
        done();
      } catch (e) {
        done(e);
      }
    });

    gateway.start().catch(() => {
      // start is expected to reject; the error event is the observable outcome
    });
  });
});