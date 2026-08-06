import { ExchangeClient } from '../src/core/engine';
import { PluginManager } from '../src/core/engine';
import { BasePlugin } from '../src/plugins/basePlugin';
import { RateLimiter } from '../src/util/rateLimiter';
import { SignatureProvider, KeyType } from '../src/auth/signatureProvider';
import { SDKError, Order, AuthCredentials } from '../src/types';
import { z } from 'zod';

class MockPlugin extends BasePlugin {
  protected readonly restMap = {
    createOrder: {
      method: 'POST',
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
    // always healthy
    return;
  }

  async callEndpoint<T = any>(key: string, params?: any): Promise<T> {
    const endpoint = this.restMap[key];
    if (!endpoint) {
      throw new SDKError(404, `Endpoint ${key} not found`);
    }
    // Simple validation using Zod
    if (endpoint.requestSchema) {
      endpoint.requestSchema.parse(params);
    }
    // Simulate a successful order creation
    const mockResponse = {
      id: 'order-123',
      symbol: params.symbol,
      side: params.side,
      type: params.type,
      price: params.price,
      quantity: params.quantity,
      status: 'new',
    };
    return mockResponse as unknown as T;
  }

  subscribe(topic: string, handler: (payload: any) => void) {
    // No WS support in mock
    return () => {};
  }
}

describe('Engine integration tests', () => {
  let client: ExchangeClient;
  let pluginManager: PluginManager;
  let mockPlugin: MockPlugin;
  const credentials: AuthCredentials = {
    apiKey: 'test-key',
    secret: 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6',
  };

  beforeEach(() => {
    pluginManager = new PluginManager();
    mockPlugin = new MockPlugin(
      {
        name: 'mock',
        baseUrl: 'https://api.mock.exchange',
        wsUrl: '',
        rateLimits: { limit: 10, intervalMs: 1000 },
        authType: 'hmac',
      },
      new (require('../src/util/eventBus').EventBus)(),
      new RateLimiter({ limit: 10, intervalMs: 1000 }),
      new SignatureProvider()
    );
    pluginManager.register('mock', mockPlugin);
    client = new ExchangeClient(pluginManager);
    client.setAuth(credentials);
  });

  test('order_successful_returns_normalized_order', async () => {
    const spyAcquire = jest.spyOn(RateLimiter.prototype, 'acquire');
    const spySign = jest.spyOn(SignatureProvider.prototype, 'sign');

    const orderParams = {
      symbol: 'BTCUSD',
      side: 'buy' as const,
      type: 'limit' as const,
      quantity: 0.1,
      price: 30000,
    };

    const response = await client.order(orderParams);
    expect(response).toMatchObject<Order>({
      id: expect.any(String),
      symbol: 'BTCUSD',
      side: 'buy',
      type: 'limit',
      price: 30000,
      quantity: 0.1,
      status: 'new',
    });

    expect(spyAcquire).toHaveBeenCalledTimes(1);
    expect(spySign).toHaveBeenCalledTimes(1);
    spyAcquire.mockRestore();
    spySign.mockRestore();
  });

  test('order_retries_on_transient_error', async () => {
    const originalCall = mockPlugin.callEndpoint.bind(mockPlugin);
    let callCount = 0;
    jest.spyOn(mockPlugin, 'callEndpoint').mockImplementation(async (key, params) => {
      callCount += 1;
      if (callCount < 3) {
        // Simulate network error
        throw new SDKError(502, 'Bad Gateway');
      }
      return originalCall(key, params);
    });

    const orderParams = {
      symbol: 'ETHUSD',
      side: 'sell' as const,
      type: 'market' as const,
      quantity: 1,
    };

    const response = await client.order(orderParams);
    expect(response.id).toBe('order-123');
    expect(callCount).toBe(3);
  });

  test('order_fails_on_4xx_error_propagates_sdk_error', async () => {
    jest.spyOn(mockPlugin, 'callEndpoint').mockRejectedValue(
      new SDKError(400, 'Invalid order parameters')
    );

    const orderParams = {
      symbol: '',
      side: 'buy' as const,
      type: 'limit' as const,
      quantity: -1,
    };

    await expect(client.order(orderParams)).rejects.toMatchObject<SDKError>({
      statusCode: 400,
      message: 'Invalid order parameters',
    });
  });

  test('plugin_manager_lookup_returns_registered_plugin', () => {
    const retrieved = pluginManager.get('mock');
    expect(retrieved).toBe(mockPlugin);
    expect(() => pluginManager.get('nonexistent')).toThrow(SDKError);
  });

  test('rate_limiter_acquire_respects_token_bucket', async () => {
    const limiter = new RateLimiter({ limit: 2, intervalMs: 500 });
    const start = Date.now();
    await limiter.acquire(); // token 1
    await limiter.acquire(); // token 2
    const acquirePromise = limiter.acquire(); // should wait for refill
    await acquirePromise;
    const elapsed = Date.now() - start;
    expect(elapsed).toBeGreaterThanOrEqual(500);
  });

  test('signature_provider_detect_and_sign_various_key_types', async () => {
    // HMAC
    const hmacSecret = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6';
    expect(SignatureProvider.detectKeyType(hmacSecret)).toBe(KeyType.HMAC);
    const hmacSig = await new SignatureProvider().sign('test', hmacSecret);
    expect(typeof hmacSig).toBe('string');

    // RSA (simple PEM stub)
    const rsaPem = `-----BEGIN RSA PRIVATE KEY-----
MIIBOgIBAAJBALe...
-----END RSA PRIVATE KEY-----`;
    expect(SignatureProvider.detectKeyType(rsaPem)).toBe(KeyType.RSA);
    const rsaSig = await new SignatureProvider().sign('test', rsaPem);
    expect(typeof rsaSig).toBe('string');

    // Ed25519 (PKCS#8 PEM stub containing OID 1.3.101.112)
    const edPem = `-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIB...
-----END PRIVATE KEY-----`;
    expect(SignatureProvider.detectKeyType(edPem)).toBe(KeyType.Ed25519);
    const edSig = await new SignatureProvider().sign('test', edPem);
    expect(typeof edSig).toBe('string');
  });
});