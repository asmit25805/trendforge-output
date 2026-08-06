# PolyTrade SDK

## Overview

PolyTrade SDK is a pluggable, exchange‑agnostic TypeScript library that unifies REST and WebSocket trading APIs. It abstracts away exchange‑specific quirks, provides high‑performance request signing, and enforces rate limits automatically. The SDK is designed for algorithmic traders, bot developers, and any application that needs to interact with multiple crypto exchanges through a single, consistent interface.

## Features

- **Plugin Architecture** – Add new exchanges without touching core code.
- **Unified API** – Same method signatures for order placement, market data, and account queries across all supported exchanges.
- **Automatic Signing** – Detects HMAC, RSA, or Ed25519 keys and signs requests with the optimal algorithm.
- **Rate‑Limit Management** – Built‑in token‑bucket limiter with optional VIP boost.
- **Event Bus** – Decoupled event handling for order updates, market data, and custom notifications.

## Installation

```bash
npm install polytrade-sdk
```

## Quick Start

```ts
import { ExchangeClient, PluginManager } from 'polytrade-sdk';
import { BasePlugin } from 'polytrade-sdk/plugins/basePlugin';
import { RateLimiter } from 'polytrade-sdk/util/rateLimiter';
import { SignatureProvider } from 'polytrade-sdk/auth/signatureProvider';
import { EventBus } from 'polytrade-sdk/util/eventBus';
import { ExchangeConfig, AuthCredentials, Order } from 'polytrade-sdk/types';

// Create core components
const eventBus = new EventBus();
const rateLimiter = new RateLimiter({ capacity: 100, intervalMs: 60000 });
const signatureProvider = new SignatureProvider('my-secret', 'hmac');
const pluginManager = new PluginManager(eventBus, rateLimiter, signatureProvider);

// Register a plugin (example implementation omitted)
// pluginManager.register('myExchange', new MyExchangePlugin(config, eventBus, rateLimiter, signatureProvider));

const client = new ExchangeClient(pluginManager, eventBus);

// Place an order
(async () => {
  const order = await client.placeOrder('myExchange', {
    symbol: 'BTC/USD',
    side: 'buy',
    type: 'limit',
    quantity: 0.1,
    price: 30000,
  });
  console.log('Order placed:', order);
})();
```

## API Reference

### Core Classes
- **ExchangeClient** – High‑level façade for interacting with registered exchange plugins.
- **PluginManager** – Registers and retrieves exchange plugins.

### Plugin Interfaces
- **BasePlugin** – Abstract class that all exchange plugins extend. Provides access to `eventBus`, `rateLimiter`, and `signatureProvider`.
- **ExchangePlugin** – Exported type describing the shape of a plugin (see `src/plugins/basePlugin.ts`).

### Utilities
- **SignatureProvider** – Handles HMAC, RSA, and Ed25519 signing.
- **RateLimiter** – Token‑bucket implementation (`TokenBucket`).
- **EventBus** – Simple publish/subscribe event system.

## Architecture

```
+-------------------+      +-------------------+      +-------------------+
|   ExchangeClient | ---> |   PluginManager   | ---> |   ExchangePlugin |
+-------------------+      +-------------------+      +-------------------+
          |                         |                         |
          v                         v                         v
   +------------+          +------------+          +-------------------+
   |  EventBus  |          | RateLimiter|          | SignatureProvider |
   +------------+          +------------+          +-------------------+
```

- **ExchangeClient** orchestrates calls to the appropriate plugin.
- **PluginManager** holds a registry of plugins keyed by exchange name.
- **ExchangePlugin** implementations expose REST endpoints and WebSocket topics.
- **EventBus** enables decoupled communication between core and plugins.
- **RateLimiter** ensures API call limits are respected.
- **SignatureProvider** signs requests according to the exchange's required algorithm.

## Contributing

Contributions are welcome! Please open issues or submit pull requests on the GitHub repository.
