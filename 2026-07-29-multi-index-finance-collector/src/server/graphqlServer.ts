import {
  GraphQLSchema,
  GraphQLObjectType,
  GraphQLString,
  GraphQLInt,
  GraphQLList,
  GraphQLNonNull,
  GraphQLUnionType,
  GraphQLInputObjectType,
  GraphQLError,
} from "graphql";
import { CacheManager } from "../core/cacheManager";
import { DataFetcher, FetchResult } from "../core/dataFetcher";
import { ProviderRegistry, IDataProvider } from "../core/providerRegistry";
import {
  Ticker,
  FinancialStatement,
  ESGScore,
  IndexDefinition,
  StatementType,
} from "../types";

/** Simple GraphQL type definitions */
const TickerType = new GraphQLObjectType({
  name: "Ticker",
  fields: {
    symbol: { type: new GraphQLNonNull(GraphQLString) },
    companyName: { type: GraphQLString },
    index: { type: GraphQLString },
  },
});

const FinancialStatementType = new GraphQLObjectType({
  name: "FinancialStatement",
  fields: {
    ticker: { type: GraphQLString },
    period: { type: GraphQLString },
    revenue: { type: GraphQLInt },
    netIncome: { type: GraphQLInt },
    statementType: { type: GraphQLString },
  },
});

const ESGScoreType = new GraphQLObjectType({
  name: "ESGScore",
  fields: {
    ticker: { type: GraphQLString },
    overall: { type: GraphQLInt },
    environment: { type: GraphQLInt },
    social: { type: GraphQLInt },
    governance: { type: GraphQLInt },
  },
});

/** Root query */
const QueryType = new GraphQLObjectType({
  name: "Query",
  fields: {
    ticker: {
      type: TickerType,
      args: { symbol: { type: new GraphQLNonNull(GraphQLString) } },
      resolve: async (_, { symbol }, { cacheManager }: { cacheManager: CacheManager }) => {
        const ticker = await cacheManager.getTicker(symbol);
        if (!ticker) {
          throw new GraphQLError(`Ticker ${symbol} not found in cache.`);
        }
        return ticker;
      },
    },
    financialStatements: {
      type: new GraphQLList(FinancialStatementType),
      args: { symbol: { type: new GraphQLNonNull(GraphQLString) } },
      resolve: async (_, { symbol }, { cacheManager, dataFetcher }: { cacheManager: CacheManager; dataFetcher: DataFetcher }) => {
        const cached = await cacheManager.getFinancialStatements(symbol);
        if (cached && cached.length > 0) {
          return cached;
        }
        // If not cached, trigger a fetch.
        const ticker = await cacheManager.getTicker(symbol);
        if (!ticker) {
          throw new GraphQLError(`Ticker ${symbol} not found.`);
        }
        const result = await dataFetcher.fetch(ticker);
        return result.financialStatements;
      },
    },
    esgScore: {
      type: ESGScoreType,
      args: { symbol: { type: new GraphQLNonNull(GraphQLString) } },
      resolve: async (_, { symbol }, { cacheManager, dataFetcher }: { cacheManager: CacheManager; dataFetcher: DataFetcher }) => {
        const cached = await cacheManager.getESGScore(symbol);
        if (cached) {
          return cached;
        }
        const ticker = await cacheManager.getTicker(symbol);
        if (!ticker) {
          throw new GraphQLError(`Ticker ${symbol} not found.`);
        }
        const result = await dataFetcher.fetch(ticker);
        return result.esgScore;
      },
    },
  },
});

/** Exported schema */
export const schema = new GraphQLSchema({ query: QueryType });

/** Simple wrapper class to start the server (used by CLI) */
export class GraphQLServer {
  constructor(
    private cacheManager: CacheManager,
    private dataFetcher: DataFetcher,
  ) {}

  async start(port: number = 4000): Promise<void> {
    const { createServer } = await import("http");
    const { graphqlHTTP } = await import("express-graphql");
    const express = await import("express");
    const app = express.default();
    app.use(
      "/graphql",
      graphqlHTTP({
        schema,
        graphiql: true,
        context: { cacheManager: this.cacheManager, dataFetcher: this.dataFetcher },
      })
    );
    return new Promise((resolve, reject) => {
      const server = createServer(app);
      server.listen(port, (err?: any) => {
        if (err) return reject(err);
        console.log(`GraphQL server running at http://localhost:${port}/graphql`);
        resolve();
      });
    });
  }
}
