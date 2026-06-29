import React, { useEffect, useState, useRef } from 'react';
import ReactDOM from 'react-dom/client';
import { EventEmitter } from 'events';
import { VirtualFS } from '../src/core/virtualFS';
import { SyncCoordinator } from '../src/core/syncCoordinator';
import { AgentAdapter } from '../src/agents/adapter';
import { TerminalEmulator } from '../src/ui/terminal';
import { PreviewEngine } from '../src/ui/preview';
import {
  Config,
  SessionOptions,
  FileChangeEvent,
  PreviewResult,
} from '../src/types';

/**
 * Simple logger that persists messages to the virtual filesystem.
 * Fatal errors are re‑thrown after logging.
 */
class Logger {
  private readonly vfs: VirtualFS;
  private readonly logPath = '/logs/app.log';

  constructor(vfs: VirtualFS) {
    this.vfs = vfs;
  }

  async info(message: string): Promise<void> {
    await this.append(`INFO ${new Date().toISOString()} ${message}`);
  }

  async warn(message: string): Promise<void> {
    await this.append(`WARN ${new Date().toISOString()} ${message}`);
  }

  async error(message: string, fatal = false): Promise<void> {
    await this.append(`ERROR ${new Date().toISOString()} ${message}`);
    if (fatal) {
      throw new Error(message);
    }
  }

  private async append(line: string): Promise<void> {
    try {
      const existing = await this.vfs.readFile(this.logPath).catch(() => '');
      const updated = existing + line + '\n';
      await this.vfs.writeFile(this.logPath, updated);
    } catch {
      // If logging fails we silently ignore to avoid recursive errors.
    }
  }
}

/**
 * Validates a Config object against a minimal JSON schema.
 * Returns the validated config or throws if validation fails.
 */
function validateConfig(raw: unknown): Config {
  if (typeof raw !== 'object' || raw === null) {
    throw new Error('Config must be an object');
  }
  const cfg = raw as Partial<Config>;

  if (!['light', 'dark'].includes(cfg.theme as any)) {
    throw new Error('Invalid theme value');
  }
  if (typeof cfg.defaultAgent !== 'string' || cfg.defaultAgent.length === 0) {
    throw new Error('defaultAgent must be a non‑empty string');
  }
  if (!Array.isArray(cfg.watchIgnore)) {
    throw new Error('watchIgnore must be an array');
  }
  if (typeof cfg.maxPreviewSize !== 'number' || cfg.maxPreviewSize <= 0) {
    throw new Error('maxPreviewSize must be a positive number');
  }

  return cfg as Config;
}

/**
 * Renders a preview for the currently selected file.
 * Subscribes to PreviewEngine updates and displays the result.
 */
function PreviewComponent({
  previewEngine,
  initialPath,
}: {
  previewEngine: PreviewEngine;
  initialPath: string;
}) {
  const [content, setContent] = useState<PreviewResult | null>(null);
  const [path, setPath] = useState<string>(initialPath);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      const result = await previewEngine.render(path);
      if (!cancelled) {
        setContent(result);
      }
    };

    load();

    const unsubscribe = previewEngine.onUpdate((updatedPath, result) => {
      if (updatedPath === path) {
        setContent(result);
      }
    });

    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [previewEngine, path]);

  if (!content) {
    return <div>Loading preview…</div>;
  }

  switch (content.type) {
    case 'html':
      return (
        <div
          dangerouslySetInnerHTML={{ __html: content.content as string }}
        />
      );
    case 'image':
      return <img src={content.content as string} alt={path} />;
    case 'pdf':
      return (
        <embed
          src={content.content as string}
          type="application/pdf"
          width="100%"
          height="100%"
        />
      );
    case 'text':
      return <pre>{content.content as string}</pre>;
    case 'error':
      return <div style={{ color: 'red' }}>{content.content as string}</div>;
    default:
      return <div>Unsupported preview type</div>;
  }
}

/**
 * Main entry point for the basic demo.
 * Sets up the virtual filesystem, sync coordinator, agent adapter,
 * terminal emulator, and preview engine.
 */
async function main(): Promise<void> {
  const vfs = new VirtualFS();
  const logger = new Logger(vfs);
  await logger.info('Demo initialization started');

  // Load configuration from IndexedDB; fall back to defaults on error.
  let config: Config;
  try {
    const raw = await vfs.readFile('/config.json');
    config = validateConfig(JSON.parse(raw));
    await logger.info('Config loaded from storage');
  } catch (e) {
    await logger.warn(`Config load failed, using defaults: ${(e as Error).message}`);
    config = {
      theme: 'light',
      defaultAgent: 'dummy-agent',
      watchIgnore: ['**/node_modules/**'],
      maxPreviewSize: 5_000_000,
    };
    await vfs.writeFile('/config.json', JSON.stringify(config));
  }

  const previewEngine = new PreviewEngine(vfs);
  const agentAdapter = new AgentAdapter(vfs);
  const syncCoordinator = new SyncCoordinator(vfs, agentAdapter, previewEngine);
  await syncCoordinator.initialize();

  // Create a root container for the UI.
  const rootDiv = document.createElement('div');
  rootDiv.id = 'codelink-root';
  rootDiv.style.display = 'flex';
  rootDiv.style.height = '100vh';
  document.body.appendChild(rootDiv);

  // Split the UI into terminal and preview panes.
  const terminalPane = document.createElement('div');
  terminalPane.style.flex = '1';
  terminalPane.style.borderRight = '1px solid #444';
  const previewPane = document.createElement('div');
  previewPane.style.flex = '1';
  rootDiv.appendChild(terminalPane);
  rootDiv.appendChild(previewPane);

  // Initialise the terminal emulator.
  const terminalEmulator = new TerminalEmulator(agentAdapter);
  const sessionOpts: SessionOptions = {
    cwd: '/',
    agentId: config.defaultAgent,
  };
  const session = await agentAdapter.startSession(sessionOpts);
  terminalEmulator.attachTo(session.id, terminalPane);
  await logger.info(`Terminal attached to session ${session.id}`);

  // Render the preview component.
  const previewRoot = ReactDOM.createRoot(previewPane);
  previewRoot.render(
    <React.StrictMode>
      <PreviewComponent previewEngine={previewEngine} initialPath="/README.md" />
    </React.StrictMode>
  );

  // Event emitter for lifecycle events.
  const lifecycle = new EventEmitter();

  lifecycle.on('sessionStarted', async (sid: string) => {
    await logger.info(`Session started: ${sid}`);
  });

  lifecycle.on('sessionEnded', async (sid: string) => {
    await logger.info(`Session ended: ${sid}`);
  });

  // Wire up agent output to the sync coordinator.
  agentAdapter.onOutput(session.id, async (data: string) => {
    // The PTY may emit file change notifications as JSON lines.
    try {
      const maybeEvent: Partial<FileChangeEvent> = JSON.parse(data);
      if (
        maybeEvent.path &&
        maybeEvent.type &&
        typeof maybeEvent.timestamp === 'number'
      ) {
        const event: FileChangeEvent = {
          path: maybeEvent.path,
          type: maybeEvent.type as 'added' | 'modified' | 'deleted',
          timestamp: maybeEvent.timestamp,
        };
        syncCoordinator.handleFileChange(event);
      }
    } catch {
      // Non‑JSON output is ignored for change detection.
    }
  });

  // Global error handling: display a full‑screen overlay on fatal errors.
  window.addEventListener('error', async (ev) => {
    const msg = ev.error instanceof Error ? ev.error.message : String(ev.message);
    await logger.error(`Fatal error: ${msg}`, true);
    const overlay = document.createElement('div');
    overlay.style.position = 'fixed';
    overlay.style.top = '0';
    overlay.style.left = '0';
    overlay.style.width = '100%';
    overlay.style.height = '100%';
    overlay.style.background = '#000';
    overlay.style.color = '#fff';
    overlay.style.display = 'flex';
    overlay.style.flexDirection = 'column';
    overlay.style.alignItems = 'center';
    overlay.style.justifyContent = 'center';
    overlay.innerHTML = `
      <h1>Unexpected error</h1>
      <p>${msg}</p>
      <button id="retry-btn">Retry</button>
    `;
    document.body.appendChild(overlay);
    document.getElementById('retry-btn')?.addEventListener('click', () => {
      location.reload();
    });
  });

  await logger.info('Demo initialization completed');
}

// Kick off the demo when the page loads.
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    main().catch((e) => console.error('Demo failed to start:', e));
  });
} else {
  main().catch((e) => console.error('Demo failed to start:', e));
}