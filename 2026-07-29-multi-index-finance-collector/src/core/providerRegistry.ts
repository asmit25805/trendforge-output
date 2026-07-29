import { Ticker, FinancialStatement, ESGScore, IndexDefinition, StatementType } from "../types";

/**
 * Interface that all data providers must implement.
 * Providers receive a ticker and index identifier and return raw JSON responses.
 * Implementations are responsible for mapping the raw response to the appropriate
 * domain models (FinancialStatement, ESGScore, etc.).
 */
export interface IDataProvider {
  /**
   * Fetch financial statements for the given ticker.
   */
  fetchFinancialStatements(ticker: Ticker, type: StatementType): Promise<FinancialStatement[]>;

  /**
   * Fetch ESG score for the given ticker.
   */
  fetchESGScore(ticker: Ticker): Promise<ESGScore>;
}

/**
 * Registry that holds all available IDataProvider implementations.
 * Consumers can register providers and later retrieve the appropriate one
 * based on the ticker's index.
 */
export class ProviderRegistry {
  private providers: Map<string, IDataProvider> = new Map();

  /** Register a provider for a specific index identifier. */
  register(indexId: string, provider: IDataProvider): void {
    if (this.providers.has(indexId)) {
      throw new Error(`Provider for index "${indexId}" is already registered.`);
    }
    this.providers.set(indexId, provider);
  }

  /** Retrieve the provider responsible for the given ticker's index. */
  getProvider(ticker: Ticker): IDataProvider {
    const provider = this.providers.get(ticker.index);
    if (!provider) {
      throw new Error(`No provider registered for index "${ticker.index}".`);
    }
    return provider;
  }
}
