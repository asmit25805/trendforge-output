import { ExchangeClient, PluginManager } from '../src/core/engine';
import { BasePlugin } from '../src/plugins/basePlugin';
import { RateLimiter } from '../src/util/rateLimiter';
import { SignatureProvider } from '../src/auth/signatureProvider';
import { EventBus } from '../src/util/eventBus';
import { ExchangeConfig, AuthCredentials, Order } from '../src/types';
import { z } from 'zod';

/**
 * Simple mock plugin used for demonstration.
 * Implements only the REST endpoint required for order creation.
 */
class DemoPlugin extends BasePlugin {
  protected readonly restMap = {
    createOrder: {
      method: 'POST' as const,
      path: '/order',
      requestSchema: z.object({
        symbol: z.string(),
        side: z.enum(['buy', 'sell']),
        type: z.enum(['limit', 'market', 'stop']),
        quantity: z.number(),
        price: z.number().optional(),
      }),
      responseSchema: z.object({
        id: z.string(),
        symbol: z.string(),
        side: z.enum(['buy', 'sell']),
        type: z.enum(['limit', 'market', 'stop']),
        price: z.number().optional(),
        quantity: z.number(),
        status: z.enum(['new', 'filled', 'canceled', 'rejected']),
      }),
    },
  };

  protected readonly wsMap = {};

  async healthCheck(): Promise<void> {
    // In a real plugin this would ping the exchange health endpoint.
    return;
  }

  async callEndpoint<T = any>(key: string, params?: any): Promise<T> {
    const endpoint = this.restMap[key];
    if (!endpoint) {
      throw new Error(`Endpoint ${key} not defined`);
    }
    // Validate request payload
    endpoint.requestSchema.parse(params);
    // Simulate a successful response
    const mockResponse = {
      id: `order-${Date.now()}`,
      symbol: params.symbol,
      side: params.side,
      type: params.type,
      price: params.price,
      quantity: params.quantity,
      status: 'new',
    };
    // Validate response shape before returning
    endpoint.responseSchema.parse(mockResponse);
    return mockResponse as unknown as T;
  }

  subscribe(topic: string, handler: (payload: any) => void): () => void {
    // No WebSocket support in this demo plugin.
    return () => {};
  }
}

/**
 * Demonstrates the typical workflow:
 *   1. Create core components.
 *   2. Register a plugin.
 *   3. Set authentication credentials.
 *   4. Place an order.
 *   5. Listen for order update events.
 */
async function main(): Promise<void> {
  // Core infrastructure
  const eventBus = new EventBus();
  const rateLimiter = new RateLimiter({ limit: 20, intervalMs: 1000 });
  const signatureProvider = new SignatureProvider();

  // Exchange configuration for the demo plugin
  const demoConfig: ExchangeConfig = {
    name: 'demo',
    baseUrl: 'https://api.demo.exchange',
    wsUrl: '',
    rateLimits: { limit: 20, intervalMs: 1000 },
    authType: 'hmac',
  };

  // Instantiate the plugin
  const demoPlugin = new DemoPlugin(demoConfig, eventBus, rateLimiter, signatureProvider);

  // Register the plugin with the manager
  const pluginManager = new PluginManager();
  pluginManager.register('demo', demoPlugin);

  // Create the high‑level client
  const client = new ExchangeClient(pluginManager);

  // Provide authentication credentials
  const credentials: AuthCredentials = {
    apiKey: 'demo-key',
    secret: '0123456789abcdef0123456789abcdef',
  };
  client.setAuth(credentials);

  // Subscribe to order updates (emitted by the client after each order call)
  const unsubscribe = client.subscribe('order:update', (payload: Order) => {
    console.log('Order update received:', payload);
  });

  // Place a limit order
  try {
    const orderParams = {
      symbol: 'BTCUSD',
      side: 'buy' as const,
      type: 'limit' as const,
      quantity: 0.01,
      price: 30000,
    };
    const orderResponse = await client.order(orderParams);
    console.log('Order placed successfully:', orderResponse);
  } catch (err) {
    // SDKError provides a structured error with status code and message
    console.error('Failed to place order:', err);
  } finally {
    // Clean up listener when no longer needed
    unsubscribe();
  }
}

// Execute the example when the script is run directly
if (require.main === module) {
  main().catch((e) => {
    console.error('Unexpected error in example:', e);
    process.exit(1);
  });
}