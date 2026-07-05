import { Database, verbose } from 'sqlite3';
import { promisify } from 'util';
import { createHash } from 'crypto';
import {
  ChainRecord,
  ChainVersionRecord,
  StepDefinition,
  RateLimits,
} from '../types.ts';

/**
 * Configuration for optional list filtering.
 */
export interface ListFilter {
  /** Maximum number of records to return. */
  limit?: number;
  /** Number of records to skip. */
  offset?: number;
}

/**
 * Persistent store for chain metadata and versions.
 */
export class CatalogStore {
  private db: Database;
  private runAsync: (sql: string, params?: any[]) => Promise<void>;
  private allAsync: (sql: string, params?: any[]) => Promise<any[]>;
  private getAsync: (sql: string, params?: any[]) => Promise<any>;

  constructor(dbPath: string) {
    verbose();
    this.db = new Database(dbPath);
    this.runAsync = promisify(this.db.run.bind(this.db));
    this.allAsync = promisify(this.db.all.bind(this.db));
    this.getAsync = promisify(this.db.get.bind(this.db));
  }

  /** List all chain records with optional pagination. */
  async listChains(filter?: ListFilter): Promise<ChainRecord[]> {
    const sql = 'SELECT * FROM chains' + (filter?.limit ? ' LIMIT ?' : '') + (filter?.offset ? ' OFFSET ?' : '');
    const params = [];
    if (filter?.limit) params.push(filter.limit);
    if (filter?.offset) params.push(filter.offset);
    return this.allAsync(sql, params);
  }

  /** Retrieve a single chain by slug. */
  async getChain(slug: string): Promise<ChainRecord | null> {
    const row = await this.getAsync('SELECT * FROM chains WHERE slug = ?', [slug]);
    return row || null;
  }

  /** Add a new chain record. */
  async addChain(record: ChainRecord): Promise<void> {
    const sql = 'INSERT INTO chains (slug, title, description) VALUES (?, ?, ?)';
    await this.runAsync(sql, [record.slug, record.title, record.description]);
  }

  /** Add a new version for a chain. */
  async addChainVersion(version: ChainVersionRecord): Promise<void> {
    const sql = 'INSERT INTO chain_versions (chain_slug, version_hash, definition, created_at) VALUES (?, ?, ?, ?)';
    await this.runAsync(sql, [
      version.chainSlug,
      version.versionHash,
      JSON.stringify(version.definition),
      version.createdAt,
    ]);
  }

  /** List versions for a given chain. */
  async listChainVersions(chainSlug: string, filter?: ListFilter): Promise<ChainVersionRecord[]> {
    const sql =
      'SELECT * FROM chain_versions WHERE chain_slug = ?' +
      (filter?.limit ? ' LIMIT ?' : '') +
      (filter?.offset ? ' OFFSET ?' : '');
    const params = [chainSlug];
    if (filter?.limit) params.push(filter.limit);
    if (filter?.offset) params.push(filter.offset);
    const rows = await this.allAsync(sql, params);
    return rows.map((row) => ({
      chainSlug: row.chain_slug,
      versionHash: row.version_hash,
      definition: JSON.parse(row.definition),
      createdAt: row.created_at,
    } as ChainVersionRecord));
  }
}

// Re‑export the type definitions so that the module's public API matches the specification.
export { ChainRecord, ChainVersionRecord };
