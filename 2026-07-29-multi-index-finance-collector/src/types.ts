import { z } from "zod";

/**
 * Represents a stock ticker belonging to a market index.
 */
export interface Ticker {
  /** Stock ticker symbol, e.g., AAPL */
  symbol: string;
  /** Full company name */
  companyName: string;
  /** Market index identifier (sp500, nasdaq100, ftse100, ...) */
  index: string;
}

/** Zod schema for runtime validation of {@link Ticker} objects. */
export const TickerSchema = z.object({
  symbol: z.string().min(1),
  companyName: z.string().min(1),
  index: z.string().min(1),
});

/**
 * Financial statement model.
 */
export interface FinancialStatement {
  ticker: string;
  period: string; // e.g., "2023-12-31"
  revenue: number;
  netIncome: number;
  statementType: "annual" | "quarterly";
}

export const FinancialStatementSchema = z.object({
  ticker: z.string(),
  period: z.string(),
  revenue: z.number().nonnegative(),
  netIncome: z.number(),
  statementType: z.enum(["annual", "quarterly"]),
});

/**
 * ESG score model.
 */
export interface ESGScore {
  ticker: string;
  overall: number;
  environment: number;
  social: number;
  governance: number;
}

export const ESGScoreSchema = z.object({
  ticker: z.string(),
  overall: z.number().min(0).max(100),
  environment: z.number().min(0).max(100),
  social: z.number().min(0).max(100),
  governance: z.number().min(0).max(100),
});

/**
 * Index definition model.
 */
export interface IndexDefinition {
  id: string;
  name: string;
  tickers: Ticker[];
}

export const IndexDefinitionSchema = z.object({
  id: z.string(),
  name: z.string(),
  tickers: z.array(TickerSchema),
});

/**
 * Helper enum for statement types used throughout the codebase.
 */
export enum StatementType {
  Annual = "annual",
  Quarterly = "quarterly",
}
