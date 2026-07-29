import { createInterface } from "readline";
import { readFile } from "fs/promises";
import { resolve } from "path";
import fetch from "node-fetch";
import { z } from "zod";

import {
  Ticker,
  IndexDefinition,
  StatementType,
} from "../types";

import { ProviderRegistry } from "../core/providerRegistry";
import { DataFetcher } from "../core/dataFetcher";
import { CacheManager } from "../core/cacheManager";
import { GraphQLServer } from "../server/graphqlServer";

/**
 * Simple command‑line engine that supports two commands:
 *   - collect: fetch data for a given index and store it in the cache.
 *   - serve: start the GraphQL server.
 */
export class CLIEngine {
  constructor(
    private providerRegistry: ProviderRegistry,
    private cacheManager: CacheManager,
    private dataFetcher: DataFetcher,
    private graphqlServer: GraphQLServer,
  ) {}

  /** Parse arguments and dispatch to the appropriate handler. */
  async run(argv: string[]): Promise<void> {
    const [, , command, ...rest] = argv;
    switch (command) {
      case "collect":
        await this.handleCollect(rest);
        break;
      case "serve":
        await this.handleServe(rest);
        break;
      default:
        console.error("Unknown command. Use 'collect' or 'serve'.");
        process.exit(1);
    }
  }

  /** Load an index definition JSON file and fetch data for each ticker. */
  private async handleCollect(args: string[]): Promise<void> {
    const indexPath = args[args.indexOf("--index") + 1];
    if (!indexPath) {
      console.error("--index <path-to-index-json> is required.");
      process.exit(1);
    }
    const absolutePath = resolve(process.cwd(), indexPath);
    const raw = await readFile(absolutePath, "utf-8");
    const indexDef = JSON.parse(raw) as IndexDefinition;

    for (const ticker of indexDef.tickers) {
      try {
        const result = await this.dataFetcher.fetch(ticker);
        console.log(`Fetched data for ${ticker.symbol}`);
      } catch (e) {
        console.error(`Failed to fetch ${ticker.symbol}:`, e);
      }
    }
    console.log("Collection complete.");
  }

  /** Start the GraphQL server on the requested port. */
  private async handleServe(args: string[]): Promise<void> {
    const portArg = args[args.indexOf("--port") + 1];
    const port = portArg ? parseInt(portArg, 10) : 4000;
    await this.graphqlServer.start(port);
  }
}
