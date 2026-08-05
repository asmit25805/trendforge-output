import { EventEmitter } from 'eventemitter3';
import { Buffer } from 'buffer';
import WebSocket from 'ws';
import {
  TaskTicket,
  TalkPayload,
  Decision,
  NegotiationResult,
} from '../types';

/**
 * Result returned by the backend runtime after executing a task.
 */
export interface RuntimeResponse {
  /** Identifier of the task that was processed. */
  taskId: string;
  /** True if the backend succeeded, false otherwise. */
  success: boolean;
  /** Optional payload returned by the backend. */
  payload?: any;
}

/**
 * RuntimeConnector manages the WebSocket connection to the backend runtime.
 * It provides a simple `sendTask` method that returns a promise resolving to a
 * `RuntimeResponse`.
 */
export class RuntimeConnector extends EventEmitter {
  private ws: WebSocket;

  constructor(url: string) {
    super();
    this.ws = new WebSocket(url);
    this.ws.on('open', () => this.emit('connected'));
    this.ws.on('close', () => this.emit('disconnected'));
    this.ws.on('error', (err) => this.emit('error', err));
  }

  /** Send a task ticket to the backend and await a response */
  sendTask(ticket: TaskTicket): Promise<RuntimeResponse> {
    return new Promise((resolve, reject) => {
      if (this.ws.readyState !== WebSocket.OPEN) {
        return reject(new Error('WebSocket is not open'));
      }
      const requestId = `req-${Date.now()}`;
      const message = JSON.stringify({ jsonrpc: '2.0', method: 'executeTask', params: ticket, id: requestId });
      const handleMessage = (data: WebSocket.Data) => {
        try {
          const response = JSON.parse(data.toString());
          if (response.id === requestId) {
            this.ws.off('message', handleMessage);
            resolve({ taskId: ticket.id, success: response.result.success, payload: response.result.payload });
          }
        } catch (e) {
          reject(e);
        }
      };
      this.ws.on('message', handleMessage);
      this.ws.send(message);
    });
  }
}
