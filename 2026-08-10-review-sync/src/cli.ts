import { Command } from 'commander'
import { spawn, execSync } from 'child_process'
import * as http from 'http'
import * as https from 'https'
import * as fs from 'fs'
import * as path from 'path'
import * as os from 'os'
import {
  ServerInfo,
  generateUuid,
  ApiError,
} from './types'
import { ReviewServer } from './server'

/**
 * CLI orchestrates user commands, ensures a singleton ReviewServer,
 * launches the sandboxed UI and forwards control commands.
 */
export class CLI {
  private static readonly CONFIG_DIR = path.join(os.homedir(), '.review-sync')
  private static readonly LOCK_FILE = path.join(CLI.CONFIG_DIR, 'server.lock')
  private serverInstance: ReviewServer | null = null
  private serverInfo: ServerInfo | null = null

  /**
   * Entry point for all sub‑commands.
   * @param argv Command‑line arguments (process.argv)
   */
  async run(argv: string[]): Promise<void> {
    const program = new Command()
    program
      .name('review-sync')
      .description('Secure offline document review with inline comments')
      .version('1.0.0')

    program
      .command('open <file>')
      .description('Open an HTML artifact for review')
      .option('-p, --port <number>', 'Preferred server port')
      .action(async (file: string, opts: { port?: string }) => {
        try {
          const info = await this.ensureServer(opts.port ? parseInt(opts.port, 10) : undefined)
          const sessionId = generateUuid()
          const token = info.token
          // Register the session directly on the server instance
          if (!this.serverInstance) {
            throw new Error('Server instance not available')
          }
          this.serverInstance.registerSession(sessionId, token)
          // Store artifact URL in session state
          const artifactUrl = pathToFileURL(file)
          this.serverInstance.getSession(sessionId)!.artifactUrl = artifactUrl
          const targetUrl = `${artifactUrl}?session=${sessionId}&token=${token}`
          this.launchBrowser(targetUrl)
        } catch (err: any) {
          console.error(`Error opening file: ${err.message}`)
          process.exit(1)
        }
      })

    program
      .command('poll')
      .description('Fetch the latest review batch')
      .option('-a, --ack', 'Acknowledge the batch after printing')
      .option('-p, --port <number>', 'Server port if not using lock file')
      .action(async (opts: { ack?: boolean; port?: string }) => {
        try {
          const info = await this.ensureServer(opts.port ? parseInt(opts.port, 10) : undefined)
          const sessionId = await this.selectSession()
          const batch = await this.fetchBatch(info, sessionId)
          if (batch) {
            console.log(JSON.stringify(batch, null, 2))
            if (opts.ack) {
              await this.ackBatch(info, sessionId)
            }
          } else {
            console.log('No pending batch.')
          }
        } catch (err: any) {
          console.error(`Polling failed: ${err.message}`)
          process.exit(1)
        }
      })

    program
      .command('status')
      .description('Print server health and active sessions')
      .action(async () => {
        try {
          const info = await this.ensureServer()
          const health = await this.fetchHealth(info)
          console.log('Server health:', health)
          const sessions = this.serverInstance?.listSessionIds() ?? []
          console.log('Active sessions:', sessions)
        } catch (err: any) {
          console.error(`Status check failed: ${err.message}`)
          process.exit(1)
        }
      })

    await program.parseAsync(argv)
  }

  /**
   * Starts the server if not already running and returns its address.
   * Retries transient errors with exponential back‑off.
   * @param port Optional preferred port.
   */
  private async ensureServer(port?: number): Promise<ServerInfo> {
    // If lock file exists, read and validate it.
    if (fs.existsSync(CLI.LOCK_FILE)) {
      try {
        const raw = fs.readFileSync(CLI.LOCK_FILE, 'utf8')
        const info: ServerInfo = JSON.parse(raw)
        // Simple liveness check – attempt a health request.
        await this.fetchHealth(info)
        this.serverInfo = info
        return info
      } catch {
        // Corrupt lock file – fall through to start a new server.
        fs.unlinkSync(CLI.LOCK_FILE)
      }
    }

    // Ensure config directory exists.
    if (!fs.existsSync(CLI.CONFIG_DIR)) {
      fs.mkdirSync(CLI.CONFIG_DIR, { recursive: true })
    }

    // Start a fresh server instance.
    this.serverInstance = new ReviewServer()
    await this.serverInstance.start(port)
    // After start, the server writes its lock file; read it back.
    const raw = fs.readFileSync(CLI.LOCK_FILE, 'utf8')
    const info: ServerInfo = JSON.parse(raw)
    this.serverInfo = info
    return info
  }

  /**
   * Opens the sandboxed UI in the default browser.
   * @param targetUrl URL containing session and token query parameters.
   */
  private launchBrowser(targetUrl: string): void {
    const platform = process.platform
    let cmd: string
    if (platform === 'darwin') {
      cmd = 'open'
    } else if (platform === 'win32') {
      cmd = 'start'
    } else {
      cmd = 'xdg-open'
    }
    try {
      execSync(`${cmd} "${targetUrl}"`, { stdio: 'ignore' })
    } catch {
      // Fallback to spawn if exec fails.
      spawn(cmd, [targetUrl], { detached: true, stdio: 'ignore' }).unref()
    }
  }

  /**
   * Retrieves a list of session IDs from the running server and prompts the user
   * to select one. For non‑interactive environments, picks the first.
   */
  private async selectSession(): Promise<string> {
    if (!this.serverInstance) {
      throw new Error('Server instance not initialized')
    }
    const ids = this.serverInstance.listSessionIds()
    if (ids.length === 0) {
      throw new Error('No active review sessions')
    }
    if (ids.length === 1) {
      return ids[0]
    }
    // Simple CLI prompt – read from stdin.
    console.log('Select a session:')
    ids.forEach((id, idx) => console.log(`[${idx + 1}] ${id}`))
    const stdin = process.stdin
    stdin.setEncoding('utf8')
    return new Promise<string>((resolve, reject) => {
      stdin.once('data', (data) => {
        const choice = parseInt(data.toString().trim(), 10)
        if (isNaN(choice) || choice < 1 || choice > ids.length) {
          reject(new Error('Invalid selection'))
        } else {
          resolve(ids[choice - 1])
        }
      })
    })
  }

  /**
   * Performs an HTTP GET to retrieve the latest batch for a session.
   * @param info Server connection details.
   * @param sessionId Identifier of the review session.
   */
  private async fetchBatch(info: ServerInfo, sessionId: string): Promise<any | null> {
    const url = `http://${info.host}:${info.port}/api/session/${encodeURIComponent(sessionId)}/batch?token=${info.token}`
    return new Promise<any>((resolve, reject) => {
      http.get(url, (res) => {
        let data = ''
        res.on('data', (chunk) => (data += chunk))
        res.on('end', () => {
          if (res.statusCode === 200) {
            try {
              const payload = JSON.parse(data)
              resolve(payload)
            } catch (e) {
              reject(new Error('Invalid JSON from server'))
            }
          } else if (res.statusCode === 204) {
            resolve(null)
          } else {
            try {
              const err: ApiError = JSON.parse(data)
              reject(new Error(`Server error ${err.code}: ${err.message}`))
            } catch {
              reject(new Error(`Unexpected server response ${res.statusCode}`))
            }
          }
        })
      }).on('error', (e) => reject(e))
    })
  }

  /**
   * Sends an acknowledgment that the batch has been processed.
   * @param info Server connection details.
   * @param sessionId Identifier of the review session.
   */
  private async ackBatch(info: ServerInfo, sessionId: string): Promise<void> {
    const url = `http://${info.host}:${info.port}/api/session/${encodeURIComponent(sessionId)}/ack?token=${info.token}`
    const payload = JSON.stringify({ ack: true })
    const options: http.RequestOptions = {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload),
      },
    }
    await new Promise<void>((resolve, reject) => {
      const req = http.request(url, options, (res) => {
        let data = ''
        res.on('data', (chunk) => (data += chunk))
        res.on('end', () => {
          if (res.statusCode === 200) {
            resolve()
          } else {
            try {
              const err: ApiError = JSON.parse(data)
              reject(new Error(`Ack failed ${err.code}: ${err.message}`))
            } catch {
              reject(new Error(`Ack failed with status ${res.statusCode}`))
            }
          }
        })
      })
      req.on('error', (e) => reject(e))
      req.write(payload)
      req.end()
    })
  }

  /**
   * Checks server health endpoint.
   * @param info Server connection details.
   */
  private async fetchHealth(info: ServerInfo): Promise<any> {
    const url = `http://${info.host}:${info.port}/health`
    return new Promise<any>((resolve, reject) => {
      http.get(url, (res) => {
        let data = ''
        res.on('data', (chunk) => (data += chunk))
        res.on('end', () => {
          if (res.statusCode === 200) {
            try {
              resolve(JSON.parse(data))
            } catch {
              reject(new Error('Malformed health response'))
            }
          } else {
            reject(new Error(`Health check failed ${res.statusCode}`))
          }
        })
      }).on('error', (e) => reject(e))
    })
  }
}

/**
 * Convert a filesystem path to a file:// URL, handling spaces and Windows backslashes.
 * @param filePath Path to the HTML artifact.
 */
function pathToFileURL(filePath: string): string {
  let absolute = path.isAbsolute(filePath) ? filePath : path.resolve(process.cwd(), filePath)
  if (process.platform === 'win32') {
    absolute = absolute.replace(/\\/g, '/')
    if (!absolute.startsWith('/')) {
      absolute = '/' + absolute
    }
  }
  return `file://${absolute}`
}

// If this module is executed directly, run the CLI.
if (require.main === module) {
  const cli = new CLI()
  cli.run(process.argv).catch((e) => {
    console.error(`Fatal error: ${e.message}`)
    process.exit(1)
  })
}