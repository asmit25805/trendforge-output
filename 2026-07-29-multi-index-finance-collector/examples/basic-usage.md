# Basic Usage

This document shows the most common workflows:

1. **Collect data for an index via the CLI**
2. **Query the cached data through the GraphQL endpoint**
3. **Check the health of the service**

---

## 1. Collect data for an index

```bash
# Install the package globally (optional)
npm install -g multi-index-finance-collector

# Or run it directly with npx
npx multi-index-finance-collector collect sp500
```

When the command starts you will see progress output similar to:

```
🔎 Processing index: sp500
🗂️  450 tickers require fetching (out of 452)
[=====---------------------------] 20/450
[==========----------------------] 100/450
...
✅ Completed index "sp500" – 450/450 fetched
```

The CLI:

* Loads the `IndexDefinition` for **sp500**.
* Downloads the ticker CSV from the configured `sourceUrl`.
* Skips any ticker that already exists in the SQLite cache.
* Calls every enabled provider in parallel, respecting each provider’s rate‑limit.
* Persists the raw JSON responses atomically.

If a provider returns a fatal 4xx error (e.g., an invalid API key), the CLI aborts with a red message:

```
Fatal error from provider "FMP": Invalid API key – check your FMP_API_KEY environment variable
```

Transient network failures are retried up to three times with exponential back‑off; the CLI continues processing the remaining tickers.

---

## 2. Query the cache via GraphQL

Start the GraphQL server (default port 4000):

```bash
npx multi-index-finance-collector serve
```

### 2.1. Retrieve a financial statement

```bash
curl -s -X POST http://localhost:4000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":"query($ticker:String!,$period:String!){financial(ticker:$ticker,period:$period){ticker period statementType currency values}}","variables":{"ticker":"AAPL","period":"2023-Q2"}}'
```

**Typical response**

```json
{
  "data": {
    "financial": {
      "ticker": "AAPL",
      "period": "2023-Q2",
      "statementType": "income",
      "currency": "USD",
      "values": {
        "revenue": 81434000000,
        "netIncome": 19954000000,
        "eps": 1.24
      }
    }
  }
}
```

If the data is stale, the response includes a `stale` flag (added by the resolver) and the server will trigger a background refresh:

```json
{
  "data": {
    "financial": {
      "ticker": "AAPL",
      "period": "2023-Q2",
      "statementType": "income",
      "currency": "USD",
      "values": { ... },
      "stale": true
    }
  }
}
```

### 2.2. Retrieve an ESG score

```bash
curl -s -X POST http://localhost:4000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":"query($ticker:String!){esg(ticker:$ticker){ticker date esgScore environmentScore socialScore governanceScore peerGroup peerScores}}","variables":{"ticker":"AAPL"}}'
```

**Typical response**

```json
{
  "data": {
    "esg": {
      "ticker": "AAPL",
      "date": "2023-12-31",
      "esgScore": 78.4,
      "environmentScore": 81.2,
      "socialScore": 75.6,
      "governanceScore": 78.0,
      "peerGroup": "Technology",
      "peerScores": {
        "MSFT": 79.1,
        "GOOG": 77.8
      }
    }
  }
}
```

If a provider throttles the request, the GraphQL error object contains a `retryAfter` hint:

```json
{
  "errors": [
    {
      "message": "Rate limit exceeded",
      "extensions": {
        "code": "RATE_LIMIT",
        "retryAfter": 30
      }
    }
  ]
}
```

---

## 3. Health check

A simple health endpoint is always available:

```bash
curl http://localhost:4000/healthz
```

**Response**

```json
{
  "status": "ok",
  "timestamp": "2026-07-29T12:34:56.789Z"
}
```

A non‑200 response indicates that the service cannot access the SQLite cache or that a required provider is mis‑configured.

---

## 4. Tips & Gotchas

| Situation                              | Action                                                                 |
|----------------------------------------|------------------------------------------------------------------------|
| **Missing API key**                    | Export the required environment variable, e.g. `export FMP_API_KEY=…` |
| **Rate‑limit hit**                     | Respect the `retryAfter` value returned in the GraphQL error.         |
| **Partial data after a crash**         | Re‑run the CLI for the same index; already‑cached rows are skipped.   |
| **Running in CI**                      | Use the in‑memory SQLite URL `:memory:` when testing.                  |

With these commands you can collect, cache, and query financial and ESG data for any supported index in a reproducible, automated way.