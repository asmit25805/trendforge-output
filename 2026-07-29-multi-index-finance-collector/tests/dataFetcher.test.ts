import { DataFetcher, FetchResult } from "../src/core/dataFetcher";
import { ProviderRegistry, IDataProvider } from "../src/core/providerRegistry";
import { CacheManager } from "../src/core/cacheManager";
import { Ticker } from "../src/types";

describe("DataFetcher", () => {
  let providerRegistry: ProviderRegistry;
  let cacheManager: CacheManager;
  let dataFetcher: DataFetcher;

  const mockTicker: Ticker = { symbol: "AAPL", companyName: "Apple Inc.", index: "sp500" };

  const mockProvider: IDataProvider = {
    async fetchFinancialStatements(ticker, type) {
      return [
        {
          ticker: ticker.symbol,
          period: "2023-12-31",
          revenue: 300_000,
          netIncome: 70_000,
          statementType: type,
        },
      ];
    },
    async fetchESGScore(ticker) {
      return {
        ticker: ticker.symbol,
        overall: 85,
        environment: 80,
        social: 90,
        governance: 85,
      };
    },
  };

  beforeEach(() => {
    providerRegistry = new ProviderRegistry();
    providerRegistry.register("sp500", mockProvider);
    cacheManager = new CacheManager(); // Assume in‑memory SQLite for tests
    dataFetcher = new DataFetcher(providerRegistry, cacheManager);
  });

  it("fetches data and returns a complete result", async () => {
    const result: FetchResult = await dataFetcher.fetch(mockTicker);
    expect(result.ticker).toBe(mockTicker.symbol);
    expect(result.financialStatements).toHaveLength(1);
    expect(result.esgScore.overall).toBeGreaterThanOrEqual(0);
  });
});
