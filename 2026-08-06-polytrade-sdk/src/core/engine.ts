import axios, { AxiosRequestConfig, Method } from 'axios';
import { z } from 'zod';
import {
  AuthCredentials,
  OrderParams,
  OrderResponse,
  SDKError,
  UnsubscribeFn,
} from '../types';
import { BasePlugin } from '../plugins/basePlugin';
import { SignatureProvider } from '../auth/signatureProvider';
import { RateLimiter } from '../util/rateLimiter';
import { EventBus } from '../util/eventBus';

/**
 * Manages registration and retrieval of exchange plugins.
 */
export class PluginManager {
  private plugins: Map<string, BasePlugin> = new Map();
  private eventBus: EventBus;
  private rateLimiter: RateLimiter;
  private signatureProvider: SignatureProvider;

  constructor(eventBus: EventBus, rateLimiter: RateLimiter, signatureProvider: SignatureProvider) {
    this.eventBus = eventBus;
    this.rateLimiter = rateLimiter;
    this.signatureProvider = signatureProvider;
  }

  register(name: string, plugin: BasePlugin): void {
    if (this.plugins.has(name)) {
      throw new SDKError(`Plugin \"${name}\" already registered`, 400);
    }
    this.plugins.set(name, plugin);
  }

  get(name: string): BasePlugin {
    const plugin = this.plugins.get(name);
    if (!plugin) {
      throw new SDKError(`Plugin \"${name}\" not found`, 404);
    }
    return plugin;
  }
}

/**
 * High‑level client used by consumers to interact with exchanges via registered plugins.
 */
export class ExchangeClient {
  private pluginManager: PluginManager;
  private eventBus: EventBus;

  constructor(pluginManager: PluginManager, eventBus: EventBus) {
    this.pluginManager = pluginManager;
    this.eventBus = eventBus;
  }

  /** Place an order on a specific exchange. */
  async placeOrder(exchange: string, params: OrderParams): Promise<OrderResponse> {
    const plugin = this.pluginManager.get(exchange);
    // Plugins are expected to implement a `placeOrder` method.
    const maybePlace = (plugin as any).placeOrder;
    if (typeof maybePlace !== 'function') {
      throw new SDKError('placeOrder not implemented for this plugin', 501);
    }
    return maybePlace.call(plugin, params);
  }

  /** Subscribe to SDK events via the shared EventBus. */
  on(event: string, listener: (payload: any) => void): UnsubscribeFn {
    return this.eventBus.on(event, listener);
  }
}
