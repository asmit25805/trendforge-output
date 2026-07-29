# multi-index-finance-collector

## Overview

`multi-index-finance-collector` is a unified command‑line interface and GraphQL service that fetches, caches, and queries financial and ESG data for multiple market indices. The tool supports bulk collection of ticker data, intelligent caching in SQLite, and on‑demand GraphQL queries that automatically refresh stale data. It is built with TypeScript, follows a pluggable provider architecture, and enforces rate‑limit awareness across all data sources.

## Features

- **Bulk CLI collection** – fetch data for an entire index with progress reporting and resume semantics.
- **GraphQL endpoint** – query financial statements or ESG scores for any cached ticker; missing data is refreshed automatically.
- **SQLite cache** – atomic upserts, incremental updates, and offline query capability.
- **Pluggable providers** – add new data sources by implementing the `IDataProvider` interface.

## Installation

```bash
npm install multi-index-finance-collector
```

You can also install globally if you intend to use the CLI directly:

```bash
npm install -g multi-index-finance-collector
```

## Quick Start

### 1. Collect data for an index via the CLI

```bash
# Collect data for the S&P 500 index
npx multi-index-finance-collector collect --index sp500
```

### 2. Run the GraphQL server

```bash
npx multi-index-finance-collector serve
```

The server will start on `http://localhost:4000/graphql`. You can explore the schema using GraphiQL.

### 3. Example GraphQL query

```graphql
query GetTicker($symbol: String!) {
  ticker(symbol: $symbol) {
    symbol
    companyName
    financialStatements {
      period
      revenue
      netIncome
    }
    esgScore {
      overall
      environment
      social
      governance
    }
  }
}
```

## Architecture

```
+-------------------+          +-------------------+          +-------------------+
|   CLI Engine      |  ---->   |   DataFetcher     |  ---->   |   ProviderRegistry |
+-------------------+          +-------------------+          +-------------------+
                                 |
                                 v
                         +-------------------+
                         |   CacheManager    |
                         +-------------------+
                                 |
                                 v
                         +-------------------+
                         |   SQLite DB       |
                         +-------------------+
                                 |
                                 v
                         +-------------------+
                         |   GraphQL Server  |
                         +-------------------+
```

- **CLI Engine** parses command‑line arguments and orchestrates collection jobs.
- **DataFetcher** coordinates provider calls, transforms raw responses, and stores results via **CacheManager**.
- **ProviderRegistry** holds registered `IDataProvider` implementations and selects the appropriate one based on the ticker/index.
- **CacheManager** abstracts SQLite interactions, handling upserts and cache‑expiry logic.
- **GraphQL Server** exposes a schema that reads from the cache and triggers on‑demand refreshes when data is stale.

## API Reference

### Types

- `Ticker`
  - `symbol: string` – Stock ticker symbol (e.g., `AAPL`).
  - `companyName: string` – Full company name.
  - `index: string` – Identifier of the market index the ticker belongs to.

- `FinancialStatement`
  - `ticker: string`
  - `period: string`
  - `revenue: number`
  - `netIncome: number`
  - `statementType: 'annual' | 'quarterly'`

- `ESGScore`
  - `ticker: string`
  - `overall: number`
  - `environment: number`
  - `social: number`
  - `governance: number`

- `IndexDefinition`
  - `id: string`
  - `name: string`
  - `tickers: Ticker[]`

### Core Classes

- `ProviderRegistry`
  - `register(provider: IDataProvider): void`
  - `getProvider(ticker: Ticker): IDataProvider`

- `DataFetcher`
  - `fetch(ticker: Ticker): Promise<FetchResult>`

- `CacheManager`
  - `upsertTicker(ticker: Ticker): Promise<void>`
  - `getTicker(symbol: string): Promise<Ticker | null>`
  - `storeFinancialStatement(stmt: FinancialStatement): Promise<void>`
  - `storeESGScore(score: ESGScore): Promise<void>`

- `GraphQLServer`
  - `start(port?: number): Promise<void>`

- `CLIEngine`
  - `run(argv: string[]): Promise<void>`

## Contributing

Contributions are welcome! Please open issues or submit pull requests.

## License

This project is licensed under the MIT License.
