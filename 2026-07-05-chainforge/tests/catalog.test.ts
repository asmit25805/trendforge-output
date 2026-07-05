import { describe, expect, test, beforeEach } from '@jest/globals';
import { CatalogStore, ListFilter } from '../src/catalog/store.ts';
import {
  ChainDefinition,
  ChainRecord,
  ChainVersionRecord,
} from '../src/types.ts';

/**
 * Helper to create a minimal valid chain definition.
 */
function makeChainDef(
  slug: string,
  versionSuffix: string = '',
): ChainDefinition {
  return {
    slug,
    title: `Test Chain ${slug}${versionSuffix}`,
    description: 'A chain used for unit testing',
    status: 'draft',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    steps: [
      {
        id: `step1${versionSuffix}`,
        type: 'script',
        payload: 'return context.input * 2;',
        inputSchema: { type: 'object', properties: { input: { type: 'number' } }, required: ['input'] },
        outputSchema: { type: 'number' },
      },
    ],
  };
}

/**
 * CatalogStore test suite.
 */
describe('CatalogStore', () => {
  let store: CatalogStore;

  beforeEach(() => {
    console.info('[Test][beforeEach] Initialising in‑memory CatalogStore');
    store = new CatalogStore(':memory:');
  });

  test('createChain stores a new chain and returns a record', async () => {
    const def = makeChainDef('alpha');
    console.info('[Test][createChain] Creating chain', def.slug);
    const record = await store.createChain(def);
    console.info('[Test][createChain] Received record', record);
    expect(record).toHaveProperty('chainSlug', 'alpha');
    expect(record).toHaveProperty('version');
    expect(record).toHaveProperty('checksum');
    expect(record.checksum).toBeDefined();
  });

  test('getChain returns the latest version when version omitted', async () => {
    const defV1 = makeChainDef('beta');
    const defV2 = makeChainDef('beta', '-v2');
    await store.createChain(defV1);
    const second = await store.createChain(defV2);
    console.info('[Test][getChain] Fetching latest version for slug beta');
    const latest = await store.getChain('beta');
    expect(latest).not.toBeNull();
    expect(latest?.version).toBe(second.version);
  });

  test('getChain returns the specified version when provided', async () => {
    const def = makeChainDef('gamma');
    const created = await store.createChain(def);
    console.info('[Test][getChain] Fetching specific version', created.version);
    const fetched = await store.getChain('gamma', created.version);
    expect(fetched).not.toBeNull();
    expect(fetched?.version).toBe(created.version);
  });

  test('createChain detects duplicate fingerprint and throws', async () => {
    const def = makeChainDef('delta');
    await store.createChain(def);
    console.info('[Test][duplicate] Attempting duplicate creation for slug delta');
    await expect(store.createChain(def)).rejects.toMatchObject({
      code: 'DUPLICATE_FINGERPRINT',
    });
  });

  test('listChains returns paginated summaries', async () => {
    const slugs = ['e1', 'e2', 'e3', 'e4', 'e5'];
    for (const s of slugs) {
      await store.createChain(makeChainDef(s));
    }
    const filter: ListFilter = { limit: 3, offset: 0 };
    console.info('[Test][listChains] Listing first page with limit 3');
    const page1 = await store.listChains(filter);
    expect(page1).toHaveLength(3);
    const page2 = await store.listChains({ limit: 3, offset: 3 });
    console.info('[Test][listChains] Listing second page with offset 3');
    expect(page2).toHaveLength(2);
  });

  test('createChain validates required fields and rejects invalid definition', async () => {
    const invalidDef: any = {
      // missing slug, title, etc.
      description: 'Invalid chain',
      status: 'draft',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      steps: [],
    };
    console.info('[Test][validation] Creating chain with missing required fields');
    await expect(store.createChain(invalidDef as ChainDefinition)).rejects.toMatchObject({
      code: 'VALIDATION_ERROR',
    });
  });
});