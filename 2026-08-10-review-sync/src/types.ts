import { randomUUID } from 'crypto'

/**
 * Minimal error object returned by all API endpoints.
 */
export interface ApiError {
  /** Machine‑readable error identifier */
  code: string
  /** Human‑readable description */
  message: string
}

/**
 * Contextual anchor used to locate a text fragment inside a document.
 */
export interface Anchor {
  /** Up to 32 characters preceding the quoted text */
  prefix: string
  /** Exact selected text */
  quote: string
  /** Up to 32 characters following the quoted text */
  suffix: string
}

/**
 * Inline comment attached to a specific anchor.
 */
export interface Comment {
  /** UUID generated on creation */
  id: string
  /** Anchor that identifies the quoted fragment */
  anchor: Anchor
  /** Identifier of the author (e.g., user name or token) */
  author: string
  /** Markdown body of the comment */
  body: string
  /** Epoch milliseconds when the comment was created */
  createdAt: number
}

/**
 * Text edit that replaces a fragment identified by an anchor.
 */
export interface Edit {
  /** UUID generated on creation */
  id: string
  /** Anchor that identifies the fragment to replace */
  anchor: Anchor
  /** New text that should replace the original fragment */
  replacement: string
  /** Identifier of the author */
  author: string
  /** Epoch milliseconds when the edit was recorded */
  timestamp: number
}

/**
 * Batch of pending comments and edits sent to an AI agent.
 */
export interface ReviewBatch {
  /** Identifier of the review session */
  sessionId: string
  /** Comments accumulated since the last batch */
  comments: Comment[]
  /** Edits accumulated since the last batch */
  edits: Edit[]
  /** Epoch milliseconds when the batch was generated */
  sentAt: number
}

/**
 * Information required by the CLI to communicate with the server.
 */
export interface ServerInfo {
  /** Loopback hostname (e.g., 127.0.0.1) */
  host: string
  /** Port on which the server listens */
  port: number
  /** Per‑session secret used for CSRF protection */
  token: string
}

/**
 * Internal mutable state of a review session.
 */
export interface ReviewSessionState {
  /** Unique identifier of the session */
  sessionId: string
  /** URL of the artifact being reviewed */
  artifactUrl: string
  /** Collected comments */
  comments: Comment[]
  /** Collected edits */
  edits: Edit[]
  /** Indicates whether new data has been added since the last flush */
  dirty: boolean
}

/**
 * Generates a RFC‑4122 version 4 UUID.
 *
 * @returns A new UUID string.
 */
export function generateUuid(): string {
  // Node 14+ provides crypto.randomUUID; fallback to manual generation if unavailable.
  if (typeof randomUUID === 'function') {
    return randomUUID()
  }
  const bytes = new Uint8Array(16)
  for (let i = 0; i < 16; ++i) {
    bytes[i] = Math.floor(Math.random() * 256)
  }
  // Set version to 4
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  // Set variant to RFC4122
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0'))
  return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`
}

/**
 * Returns the current timestamp in epoch milliseconds.
 *
 * @returns Current time as a number.
 */
export function now(): number {
  return Date.now()
}

/**
 * Creates a standardized API error object.
 *
 * @param code Machine‑readable error identifier.
 * @param message Human‑readable description.
 * @returns An ApiError instance.
 */
export function createApiError(code: string, message: string): ApiError {
  return { code, message }
}

/**
 * Resolves an anchor against a new document text, returning the start offset
 * of the original quote if it can be located, otherwise `null`.
 *
 * @param anchor Anchor to resolve.
 * @param newText Full text of the updated document.
 * @returns Zero‑based index of the quote or `null` if not found.
 */
export function resolveAnchor(anchor: Anchor, newText: string): number | null {
  const { prefix, quote, suffix } = anchor
  // Build a tolerant search pattern: prefix + quote + suffix, allowing missing context.
  const pattern = `${quote}`
  const index = newText.indexOf(pattern)
  if (index === -1) {
    return null
  }
  // Verify surrounding context if available.
  if (prefix) {
    const before = newText.slice(Math.max(0, index - prefix.length), index)
    if (!before.endsWith(prefix)) {
      return null
    }
  }
  if (suffix) {
    const after = newText.slice(index + quote.length, index + quote.length + suffix.length)
    if (!after.startsWith(suffix)) {
      return null
    }
  }
  return index
}

/**
 * Creates an anchor from raw text and a selection range.
 *
 * @param text Full document text.
 * @param start Zero‑based start offset of the selection.
 * @param end Zero‑based end offset (exclusive) of the selection.
 * @returns An Anchor containing prefix, quote, and suffix.
 */
export function createAnchor(text: string, start: number, end: number): Anchor {
  const quote = text.slice(start, end)
  const prefixStart = Math.max(0, start - 32)
  const suffixEnd = Math.min(text.length, end + 32)
  const prefix = text.slice(prefixStart, start)
  const suffix = text.slice(end, suffixEnd)
  return { prefix, quote, suffix }
}

/**
 * Represents a single review session and provides methods to mutate its state.
 */
export class ReviewSession {
  private state: ReviewSessionState

  /**
   * Constructs a new ReviewSession.
   *
   * @param sessionId Unique identifier for the session.
   * @param artifactUrl URL of the HTML artifact to review.
   */
  constructor(sessionId: string, artifactUrl: string) {
    this.state = {
      sessionId,
      artifactUrl,
      comments: [],
      edits: [],
      dirty: false
    }
  }

  /**
   * Returns the underlying session identifier.
   */
  get sessionId(): string {
    return this.state.sessionId
  }

  /**
   * Returns the URL of the artifact associated with this session.
   */
  get artifactUrl(): string {
    return this.state.artifactUrl
  }

  /**
   * Appends a new comment to the session and marks it dirty.
   *
   * @param comment Comment to add.
   */
  addComment(comment: Comment): void {
    this.state.comments.push(comment)
    this.state.dirty = true
  }

  /**
   * Applies an edit to the in‑memory representation of the artifact.
   *
   * @param edit Edit to apply.
   */
  applyEdit(edit: Edit): void {
    this.state.edits.push(edit)
    this.state.dirty = true
  }

  /**
   * Packages all pending comments and edits into a ReviewBatch, resets dirty flags,
   * and clears the pending collections.
   *
   * @returns A ReviewBatch ready for consumption by an AI agent.
   */
  flush(): ReviewBatch {
    const batch: ReviewBatch = {
      sessionId: this.state.sessionId,
      comments: this.state.comments,
      edits: this.state.edits,
      sentAt: now()
    }
    // Reset pending collections but keep session metadata.
    this.state.comments = []
    this.state.edits = []
    this.state.dirty = false
    return batch
  }

  /**
   * Indicates whether the session has unflushed data.
   *
   * @returns `true` if new comments or edits exist, otherwise `false`.
   */
  isDirty(): boolean {
    return this.state.dirty
  }

  /**
   * Retrieves a shallow copy of the current comments.
   *
   * @returns Array of Comment objects.
   */
  getComments(): Comment[] {
    return [...this.state.comments]
  }

  /**
   * Retrieves a shallow copy of the current edits.
   *
   * @returns Array of Edit objects.
   */
  getEdits(): Edit[] {
    return [...this.state.edits]
  }
}

/**
 * Validates that an object conforms to the Comment interface.
 *
 * @param obj Object to validate.
 * @returns `true` if valid, otherwise `false`.
 */
export function isValidComment(obj: unknown): obj is Comment {
  if (typeof obj !== 'object' || obj === null) return false
  const c = obj as Partial<Comment>
  return (
    typeof c.id === 'string' &&
    typeof c.author === 'string' &&
    typeof c.body === 'string' &&
    typeof c.createdAt === 'number' &&
    isValidAnchor(c.anchor)
  )
}

/**
 * Validates that an object conforms to the Edit interface.
 *
 * @param obj Object to validate.
 * @returns `true` if valid, otherwise `false`.
 */
export function isValidEdit(obj: unknown): obj is Edit {
  if (typeof obj !== 'object' || obj === null) return false
  const e = obj as Partial<Edit>
  return (
    typeof e.id === 'string' &&
    typeof e.author === 'string' &&
    typeof e.replacement === 'string' &&
    typeof e.timestamp === 'number' &&
    isValidAnchor(e.anchor)
  )
}

/**
 * Validates that an object conforms to the Anchor interface.
 *
 * @param obj Object to validate.
 * @returns `true` if valid, otherwise `false`.
 */
export function isValidAnchor(obj: unknown): obj is Anchor {
  if (typeof obj !== 'object' || obj === null) return false
  const a = obj as Partial<Anchor>
  return (
    typeof a.prefix === 'string' &&
    typeof a.quote === 'string' &&
    typeof a.suffix === 'string'
  )
}

/**
 * Validates that an object conforms to the ReviewBatch interface.
 *
 * @param obj Object to validate.
 * @returns `true` if valid, otherwise `false`.
 */
export function isValidReviewBatch(obj: unknown): obj is ReviewBatch {
  if (typeof obj !== 'object' || obj === null) return false
  const b = obj as Partial<ReviewBatch>
  return (
    typeof b.sessionId === 'string' &&
    typeof b.sentAt === 'number' &&
    Array.isArray(b.comments) &&
    b.comments.every(isValidComment) &&
    Array.isArray(b.edits) &&
    b.edits.every(isValidEdit)
  )
}

/**
 * Validates that an object conforms to the ServerInfo interface.
 *
 * @param obj Object to validate.
 * @returns `true` if valid, otherwise `false`.
 */
export function isValidServerInfo(obj: unknown): obj is ServerInfo {
  if (typeof obj !== 'object' || obj === null) return false
  const s = obj as Partial<ServerInfo>
  return (
    typeof s.host === 'string' &&
    typeof s.port === 'number' &&
    typeof s.token === 'string'
  )
}