import express, { Request, Response, NextFunction, Application } from 'express'
import http, { Server as HttpServer } from 'http'
import { randomUUID } from 'crypto'
import { promises as fs } from 'fs'
import path from 'path'
import os from 'os'
import { ReviewSessionState, ServerInfo, ApiError, generateUuid } from './types'
import router from './router'

/**
 * ReviewServer manages the HTTP server lifecycle, routes API calls,
 * and coordinates state between the CLI, UI, and AI agents.
 */
export class ReviewServer {
  private app: Application
  private httpServer: HttpServer | null = null
  private sessions: Map<string, { token: string; state: ReviewSessionState }> = new Map()
  private lockFilePath: string

  constructor() {
    this.app = express()
    this.app.use(express.json({ limit: '1mb' }))
    this.app.use(this.errorHandler.bind(this))
    this.app.use('/api', router)
    this.app.get('/health', (_req: Request, res: Response) => res.json({ status: 'ok' }))

    const configDir = path.join(os.homedir(), '.review-sync')
    this.lockFilePath = path.join(configDir, 'server.lock')
  }

  /**
   * Starts the server on a free port (or the given port) and registers health checks.
   * Retries on transient errors with exponential back‑off.
   */
  async start(port?: number): Promise<void> {
    await this.ensureLockFile()
    const maxAttempts = 5
    let attempt = 0
    let delay = 100

    while (attempt < maxAttempts) {
      try {
        const listenPort = port ?? 0 // 0 => random free port
        await new Promise<void>((resolve, reject) => {
          this.httpServer = this.app.listen(listenPort, '127.0.0.1', () => resolve())
          this.httpServer?.once('error', (err) => reject(err))
        })
        const address = this.httpServer?.address()
        if (address && typeof address === 'object') {
          const info: ServerInfo = {
            host: address.address,
            port: address.port,
            token: generateUuid(),
          }
          await this.writeLockFile(info)
          console.log(`ReviewServer listening on http://${info.host}:${info.port}`)
        }
        return
      } catch (err: any) {
        attempt++
        if (attempt >= maxAttempts) {
          console.error(`Failed to start server after ${maxAttempts} attempts: ${err.message}`)
          await this.shutdown()
          process.exit(1)
        }
        await this.delay(delay)
        delay *= 2
      }
    }
  }

  /**
   * Gracefully shuts down the HTTP server and removes the lock file.
   */
  async stop(): Promise<void> {
    await this.shutdown()
  }

  /**
   * Registers a new review session with its token.
   */
  registerSession(sessionId: string, token: string): void {
    if (this.sessions.has(sessionId)) {
      throw new Error(`Session ${sessionId} already exists`)
    }
    const state: ReviewSessionState = {
      sessionId,
      artifactUrl: '',
      comments: [],
      edits: [],
      dirty: false,
    }
    this.sessions.set(sessionId, { token, state })
  }

  /**
   * Retrieves the mutable state for a session, or undefined if not found.
   */
  getSession(sessionId: string): ReviewSessionState | undefined {
    const entry = this.sessions.get(sessionId)
    return entry?.state
  }

  /**
   * Validates a token for a given session.
   */
  validateToken(sessionId: string, token: string): boolean {
    const entry = this.sessions.get(sessionId)
    return entry?.token === token
  }

  /**
   * Internal: writes server info to the lock file for CLI discovery.
   */
  private async writeLockFile(info: ServerInfo): Promise<void> {
    const dir = path.dirname(this.lockFilePath)
    await fs.mkdir(dir, { recursive: true })
    await fs.writeFile(this.lockFilePath, JSON.stringify(info), { encoding: 'utf8' })
  }

  /**
   * Internal: ensures the lock file directory exists.
   */
  private async ensureLockFile(): Promise<void> {
    const dir = path.dirname(this.lockFilePath)
    await fs.mkdir(dir, { recursive: true })
  }

  /**
   * Internal: removes the lock file.
   */
  private async removeLockFile(): Promise<void> {
    try {
      await fs.unlink(this.lockFilePath)
    } catch {
      // ignore if already removed
    }
  }

  /**
   * Internal: shuts down the HTTP server and cleans up resources.
   */
  private async shutdown(): Promise<void> {
    if (this.httpServer) {
      await new Promise<void>((resolve) => this.httpServer?.close(() => resolve()))
      this.httpServer = null
    }
    await this.removeLockFile()
  }

  /**
   * Internal: generic error handler returning standardized ApiError objects.
   */
  private errorHandler(err: any, _req: Request, res: Response, _next: NextFunction): void {
    const apiError: ApiError = {
      code: err.code ?? 'internal_error',
      message: err.message ?? 'An unexpected error occurred',
    }
    const status = err.status ?? 500
    res.status(status).json(apiError)
  }

  /**
   * Internal: simple delay helper.
   */
  private async delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
  }
}