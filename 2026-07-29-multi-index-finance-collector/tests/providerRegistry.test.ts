import { ProviderRegistry, IDataProvider } from "../src/core/providerRegistry";
import { Ticker } from "../src/types";

describe("ProviderRegistry", () => {
  const registry = new ProviderRegistry();

  const mockProvider: IDataProvider = {
    async fetchFinancialStatements(ticker: Ticker, type) {
      return [];
    },
    async fetchESGScore(ticker: Ticker) {
      return { ticker: ticker.symbol, overall: 50, environment: 50, social: 50, governance: 50 };
    },
  };

  it("registers and retrieves a provider", () => {
    registry.register("sp500", mockProvider);
    const ticker: Ticker = { symbol: "AAPL", companyName: "Apple Inc.", index: "sp500" };
    const provider = registry.getProvider(ticker);
    expect(provider).toBe(mockProvider);
  });

  it("throws when requesting an unregistered index", () => {
    const ticker: Ticker = { symbol: "MSFT", companyName: "Microsoft Corp.", index: "nasdaq100" };
    expect(() => registry.getProvider(ticker)).toThrowError(/No provider registered/);
  });
});
