import { Ticker, FinancialStatement, ESGScore, IndexDefinition, StatementType } from "../types";
import { ProviderRegistry, IDataProvider } from "./providerRegistry";
import { CacheManager } from "./cacheManager";

/**
 * Result of a complete fetch operation for a ticker.
 */
export interface FetchResult {
  /** The ticker symbol that was processed. */
  ticker: string;
  /** Index identifier associated with the ticker. */
  index: string;
  /** Financial statements that were fetched. */
  financialStatements: FinancialStatement[];
  /** ESG score that was fetched. */
  esgScore: ESGScore;
}

/**
 * DataFetcher coordinates providers, caching and refresh logic.
 */
export class DataFetcher {
  constructor(
    private providerRegistry: ProviderRegistry,
    private cacheManager: CacheManager,
  ) {}

  /**
   * Fetch all data for a given ticker, store it in the cache, and return the result.
   */
  async fetch(ticker: Ticker): Promise<FetchResult> {
    const provider = this.providerRegistry.getProvider(ticker);

    // Attempt to retrieve cached data first.
    const cachedStatements = await this.cacheManager.getFinancialStatements(ticker.symbol);
    const cachedESG = await this.cacheManager.getESGScore(ticker.symbol);

    // Determine if we need to refresh data.
    const needStatements = !cachedStatements || cachedStatements.length === 0;
    const needESG = !cachedESG;

    const [financialStatements, esgScore] = await Promise.all([
      needStatements ? provider.fetchFinancialStatements(ticker, StatementType.Annual) : Promise.resolve(cachedStatements!),
      needESG ? provider.fetchESGScore(ticker) : Promise.resolve(cachedESG!),
    ]);

    // Persist fresh data.
    if (needStatements) {
      await this.cacheManager.upsertFinancialStatements(financialStatements);
    }
    if (needESG) {
      await this.cacheManager.upsertESGScore(esgScore);
    }

    return {
      ticker: ticker.symbol,
      index: ticker.index,
      financialStatements,
      esgScore,
    };
  }
}
