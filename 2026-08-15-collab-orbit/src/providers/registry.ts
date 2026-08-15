import { DeployProvider, DeployConfig } from '../types';
import { logger } from '../utils/logger';
import retry from 'p-retry';

/**
 * Error thrown when a requested provider cannot be found in the registry.
 */
export class ProviderNotFoundError extends Error {
  /** @param id Identifier of the missing provider */
  constructor(id: string) {
    super(`Provider "${id}" not found`);
    this.name = 'ProviderNotFoundError';
  }
}

/**
 * Registry that holds deployment providers.
 */
export class ProviderRegistry {
  private readonly providers: Map<string, DeployProvider> = new Map();

  /** Register a provider. */
  register(provider: DeployProvider): void {
    if (this.providers.has(provider.id)) {
      logger.warn(`Provider "${provider.id}" is being overridden`);
    }
    this.providers.set(provider.id, provider);
  }

  /** Retrieve a provider by its identifier. */
  get(id: string): DeployProvider {
    const provider = this.providers.get(id);
    if (!provider) {
      throw new ProviderNotFoundError(id);
    }
    return provider;
  }

  /** Deploy using a specific provider with retry logic. */
  async deploy(id: string, config: DeployConfig): Promise<void> {
    const provider = this.get(id);
    await retry(() => provider.deploy(config), { retries: 3 });
  }
}
