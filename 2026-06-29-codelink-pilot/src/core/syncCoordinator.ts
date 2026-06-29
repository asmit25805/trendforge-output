import { VirtualFS } from './virtualFS';
import { PreviewEngine } from '../ui/preview';
import { Config, FileChangeEvent } from '../types';

/**
 * Coordinates state between VirtualFS, PreviewEngine, and persisted configuration.
 */
export class SyncCoordinator {
  private readonly virtualFS: VirtualFS;
  private readonly previewEngine: PreviewEngine;
  private config: Config;

  /** Queue of pending file change events awaiting debounce. */
  private pendingEvents: FileChangeEvent[] = [];

  /** Debounce timer identifier. */
  private debounceTimer: number | null = null;

  /** Milliseconds to wait before processing accumulated file changes. */
  private readonly debounceDelay = 200;

  /** IndexedDB database name used for persisting configuration. */
  private static readonly DB_NAME = 'codelink-pilot-config';
  /** Object store name within the IndexedDB database. */
  private static readonly STORE_NAME = 'settings';
  /** Key under which the configuration object is stored. */
  private static readonly CONFIG_KEY = 'config';

  /**
   * Creates a new SyncCoordinator.
   *
   * @param virtualFS   Instance providing file‑system operations.
   * @param previewEngine Engine responsible for rendering live previews.
   * @param initialConfig User configuration loaded elsewhere.
   */
  constructor(virtualFS: VirtualFS, previewEngine: PreviewEngine, initialConfig: Config) {
    this.virtualFS = virtualFS;
    this.previewEngine = previewEngine;
    this.config = initialConfig;
  }

  /**
   * Sets up file‑system watchers and prepares the coordinator for runtime.
   */
  async initialize(): Promise<void> {
    // Register a recursive watch on the root of the virtual file system.
    const unsubscribe = this.virtualFS.watch('/', (event: FileChangeEvent) => {
      this.handleFileChange(event);
    });

    // Ensure the watcher is removed when the page unloads.
    window.addEventListener('beforeunload', () => {
      unsubscribe();
    });

    // Load any persisted configuration; if none exists, persist the supplied one.
    try {
      const persisted = await this.loadPersistedConfig();
      if (persisted) {
        this.config = persisted;
      } else {
        await this.persistConfig();
      }
    } catch (err) {
      console.error('SyncCoordinator initialization error while loading config:', err);
    }
  }

  /**
   * Handles a single file‑change event by adding it to the debounce queue.
   *
   * @param event Details of the file change.
   */
  handleFileChange(event: FileChangeEvent): void {
    this.pendingEvents.push(event);
    if (this.debounceTimer !== null) {
      clearTimeout(this.debounceTimer);
    }
    this.debounceTimer = window.setTimeout(() => this.flushPendingEvents(), this.debounceDelay);
  }

  /**
   * Flushes all queued file‑change events, invoking the preview engine for each
   * distinct path. Errors are logged but do not interrupt processing of other events.
   */
  private async flushPendingEvents(): Promise<void> {
    const eventsToProcess = this.pendingEvents;
    this.pendingEvents = [];
    this.debounceTimer = null;

    // Collapse events by path, keeping the most recent type.
    const latestByPath = new Map<string, FileChangeEvent>();
    for (const ev of eventsToProcess) {
      latestByPath.set(ev.path, ev);
    }

    for (const ev of latestByPath.values()) {
      try {
        await this.previewEngine.updateOnChange(ev);
      } catch (err) {
        console.error(`PreviewEngine failed to update for ${ev.path}:`, err);
        // Continue processing remaining events.
      }
    }
  }

  /**
   * Persists the current configuration to IndexedDB.
   */
  async persistConfig(): Promise<void> {
    const db = await this.openDatabase();
    const tx = db.transaction(SyncCoordinator.STORE_NAME, 'readwrite');
    const store = tx.objectStore(SyncCoordinator.STORE_NAME);
    store.put(this.config, SyncCoordinator.CONFIG_KEY);
    await tx.complete;
    db.close();
  }

  /**
   * Loads persisted configuration from IndexedDB, if present.
   *
   * @returns The stored Config object or null if none exists.
   */
  private async loadPersistedConfig(): Promise<Config | null> {
    const db = await this.openDatabase();
    const tx = db.transaction(SyncCoordinator.STORE_NAME, 'readonly');
    const store = tx.objectStore(SyncCoordinator.STORE_NAME);
    const request = store.get(SyncCoordinator.CONFIG_KEY);
    const result = await new Promise<any>((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    await tx.complete;
    db.close();
    return result ?? null;
  }

  /**
   * Opens (or creates) the IndexedDB database used for configuration storage.
   *
   * @returns An open IDBDatabase instance.
   */
  private async openDatabase(): Promise<IDBDatabase> {
    return new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(SyncCoordinator.DB_NAME, 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(SyncCoordinator.STORE_NAME)) {
          db.createObjectStore(SyncCoordinator.STORE_NAME);
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }
}