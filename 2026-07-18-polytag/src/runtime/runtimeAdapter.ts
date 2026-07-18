import { spawn } from 'child_process';
import { request as httpRequest } from 'http';
import { request as httpsRequest } from 'https';
import { URL } from 'url';
import { randomUUID } from 'crypto';
import {
  RuntimeAdapter,
  RuntimeResult,
  TaskDefinition,
  ExecutionContext,
  AuditRecord,
  Platform,
  MessageContent,
  TargetRef,
  ApprovalPayload,
} from '../types.ts';
import { AuditLogger } from '../store/knowledgeStore.ts';

/**
 * Base class providing common audit‑logging utilities.
 */
abstract class BaseAdapter implements RuntimeAdapter {
  protected readonly auditLogger: AuditLogger;
  protected readonly dryRun: boolean;

  constructor(dryRun = false) {
    this.auditLogger = new AuditLogger();
    this.dryRun = dryRun;
  }

  abstract supportsCapability(cap: string): boolean;
  abstract execute(task: TaskDefinition, context: ExecutionContext): Promise<RuntimeResult>;

  /**
   * Persists a run record. If a record with the same runId already exists,
   * the method updates the endTime and status, preserving idempotency.
   */
  protected async logRun(record: AuditRecord): Promise<void> {
    console.log(`BaseAdapter: logging run ${record.runId} with status ${record.status}`);
    await this.auditLogger.logRun(record);
  }

  /**
   * Checks whether a run with the given ID already exists.
   */
  protected async isDuplicateRun(runId: string): Promise<boolean> {
    const existing = await this.auditLogger.getRecord(runId);
    return !!existing;
  }
}

/**
 * Executes a command‑line program and normalises its output.
 *
 * Capabilities are declared at construction time; `supportsCapability` checks
 * against that list.
 *
 * Example:
 *   const cli = new GenericCliAdapter('python', ['script.py'], ['network']);
 */
export class GenericCliAdapter extends BaseAdapter {
  private readonly command: string;
  private readonly args: string[];
  private readonly capabilities: Set<string>;
  private readonly timeoutMs: number;

  constructor(
    command: string,
    args: string[] = [],
    capabilities: string[] = [],
    timeoutMs = 30_000,
    dryRun = false,
  ) {
    super(dryRun);
    this.command = command;
    this.args = args;
    this.capabilities = new Set(capabilities);
    this.timeoutMs = timeoutMs;
  }

  supportsCapability(cap: string): boolean {
    const result = this.capabilities.has(cap);
    console.log(`GenericCliAdapter: capability "${cap}" supported = ${result}`);
    return result;
  }

  async execute(task: TaskDefinition, context: ExecutionContext): Promise<RuntimeResult> {
    console.log(`GenericCliAdapter: executing task ${task.taskId}`);

    if (await this.isDuplicateRun(task.taskId)) {
      console.log(`GenericCliAdapter: duplicate run detected for ${task.taskId}, skipping execution`);
      return { output: '', error: null, metadata: { durationMs: 0 } };
    }

    if (this.dryRun) {
      console.log('GenericCliAdapter: dry‑run mode – no external process will be started');
      const dryResult: RuntimeResult = {
        output: `Dry run: would execute "${this.command} ${this.args.join(' ')}"`,
        error: null,
        metadata: { durationMs: 0 },
      };
      await this.logRun({
        runId: task.taskId,
        runtimeId: `${this.command}-dry`,
        startTime: Date.now(),
        endTime: Date.now(),
        status: 'success',
        output: dryResult.output,
        errorMessage: null,
        approvalId: null,
      });
      return dryResult;
    }

    const startTime = Date.now();
    let stdout = '';
    let stderr = '';
    let timedOut = false;

    const child = spawn(this.command, this.args, { env: process.env });

    const timeoutHandle = setTimeout(() => {
      timedOut = true;
      child.kill('SIGKILL');
    }, this.timeoutMs);

    child.stdout.on('data', (data: Buffer) => {
      stdout += data.toString();
    });

    child.stderr.on('data', (data: Buffer) => {
      stderr += data.toString();
    });

    const exitCode: number = await new Promise((resolve) => {
      child.on('close', (code) => resolve(code ?? -1));
    });

    clearTimeout(timeoutHandle);
    const durationMs = Date.now() - startTime;

    const error = timedOut
      ? `Process timed out after ${this.timeoutMs} ms`
      : exitCode !== 0
        ? `Process exited with code ${exitCode}: ${stderr.trim()}`
        : null;

    const result: RuntimeResult = {
      output: stdout.trim(),
      error,
      metadata: { durationMs },
    };

    await this.logRun({
      runId: task.taskId,
      runtimeId: this.command,
      startTime,
      endTime: Date.now(),
      status: error ? 'error' : 'success',
      output: result.output,
      errorMessage: error,
      approvalId: null,
    });

    console.log(`GenericCliAdapter: task ${task.taskId} completed in ${durationMs} ms`);
    return result;
  }
}

/**
 * Performs an HTTP request and normalises the response.
 *
 * Capabilities are declared at construction time; `supportsCapability` checks
 * against that list.
 *
 * Example:
 *   const http = new HttpAdapter('https://api.example.com/v1', 'POST', ['network']);
 */
export class HttpAdapter extends BaseAdapter {
  private readonly baseUrl: string;
  private readonly method: string;
  private readonly headers: Record<string, string>;
  private readonly capabilities: Set<string>;
  private readonly timeoutMs: number;

  constructor(
    baseUrl: string,
    method: string = 'GET',
    headers: Record<string, string> = {},
    capabilities: string[] = [],
    timeoutMs = 15_000,
    dryRun = false,
  ) {
    super(dryRun);
    this.baseUrl = baseUrl;
    this.method = method.toUpperCase();
    this.headers = { ...headers };
    this.capabilities = new Set(capabilities);
    this.timeoutMs = timeoutMs;
  }

  supportsCapability(cap: string): boolean {
    const result = this.capabilities.has(cap);
    console.log(`HttpAdapter: capability "${cap}" supported = ${result}`);
    return result;
  }

  async execute(task: TaskDefinition, context: ExecutionContext): Promise<RuntimeResult> {
    console.log(`HttpAdapter: executing task ${task.taskId}`);

    if (await this.isDuplicateRun(task.taskId)) {
      console.log(`HttpAdapter: duplicate run detected for ${task.taskId}, skipping execution`);
      return { output: '', error: null, metadata: { durationMs: 0 } };
    }

    if (this.dryRun) {
      console.log('HttpAdapter: dry‑run mode – no network request will be sent');
      const dryResult: RuntimeResult = {
        output: `Dry run: would send ${this.method} request to ${this.baseUrl}`,
        error: null,
        metadata: { durationMs: 0 },
      };
      await this.logRun({
        runId: task.taskId,
        runtimeId: `${this.baseUrl}-dry`,
        startTime: Date.now(),
        endTime: Date.now(),
        status: 'success',
        output: dryResult.output,
        errorMessage: null,
        approvalId: null,
      });
      return dryResult;
    }

    const startTime = Date.now();

    const url = new URL(this.baseUrl);
    const isHttps = url.protocol === 'https:';
    const requestFn = isHttps ? httpsRequest : httpRequest;

    const payload = JSON.stringify({
      taskId: task.taskId,
      prompt: task.prompt,
      knowledgeVersion: task.knowledgeVersion,
    });

    const options = {
      method: this.method,
      hostname: url.hostname,
      port: url.port,
      path: url.pathname + url.search,
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload),
        ...this.headers,
      },
      timeout: this.timeoutMs,
    };

    const responseBody = await new Promise<string>((resolve, reject) => {
      const req = requestFn(options, (res) => {
        let data = '';
        res.on('data', (chunk) => {
          data += chunk;
        });
        res.on('end', () => {
          resolve(data);
        });
      });

      req.on('error', (err) => {
        reject(err);
      });

      req.on('timeout', () => {
        req.destroy(new Error('Request timed out'));
      });

      req.write(payload);
      req.end();
    }).catch((err) => {
      return Promise.reject(err);
    });

    const durationMs = Date.now() - startTime;

    const result: RuntimeResult = {
      output: responseBody,
      error: null,
      metadata: { durationMs },
    };

    await this.logRun({
      runId: task.taskId,
      runtimeId: `${this.method} ${this.baseUrl}`,
      startTime,
      endTime: Date.now(),
      status: 'success',
      output: result.output,
      errorMessage: null,
      approvalId: null,
    });

    console.log(`HttpAdapter: task ${task.taskId} completed in ${durationMs} ms`);
    return result;
  }
}

/**
 * Simple in‑memory queue to allow concurrent execution of multiple adapters
 * while preserving order per taskId.  The queue is bounded to avoid unbounded
 * memory growth.
 */
export class RuntimeQueue {
  private readonly maxConcurrent: number;
  private activeCount = 0;
  private readonly pending: Array<() => Promise<void>> = [];

  constructor(maxConcurrent = 4) {
    this.maxConcurrent = maxConcurrent;
  }

  /**
   * Enqueues a runtime execution.  The returned promise resolves when the
   * execution finishes.
   */
  async enqueue<T>(fn: () => Promise<T>): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      const run = async () => {
        this.activeCount++;
        try {
          const result = await fn();
          resolve(result);
        } catch (e) {
          reject(e);
        } finally {
          this.activeCount--;
          this.dequeue();
        }
      };
      if (this.activeCount < this.maxConcurrent) {
        run();
      } else {
        this.pending.push(run);
      }
    });
  }

  private dequeue(): void {
    if (this.pending.length === 0) {
      return;
    }
    if (this.activeCount < this.maxConcurrent) {
      const next = this.pending.shift()!;
      next();
    }
  }
}

/**
 * Exported symbols for external consumption.
 */
export {
  RuntimeQueue,
};