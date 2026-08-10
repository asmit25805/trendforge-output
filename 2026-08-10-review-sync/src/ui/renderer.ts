import { generateUuid, Comment, Anchor, Edit, ApiError } from '../types'

/**
 * Utility to safely slice a string ensuring we do not split surrogate pairs.
 */
function safeSlice(str: string, start: number, end: number): string {
  return str.slice(start, end)
}

/**
 * AnchorResolver provides robust creation and resolution of text anchors.
 * It stores a fixed‑size context (up to 32 characters) before and after the quoted text.
 */
export class AnchorResolver {
  /** Maximum length of prefix/suffix context */
  private static readonly CONTEXT_SIZE = 32

  /**
   * Creates an Anchor from the given full text and selection offsets.
   *
   * @param text  The complete document text.
   * @param start Index of the first selected character.
   * @param end   Index after the last selected character.
   * @returns     An Anchor containing prefix, quote, and suffix.
   */
  static createAnchor(text: string, start: number, end: number): Anchor {
    if (start < 0 || end > text.length || start >= end) {
      const err: ApiError = { code: 'INVALID_SELECTION', message: 'Selection indices are out of bounds' }
      throw err
    }

    const prefixStart = Math.max(0, start - AnchorResolver.CONTEXT_SIZE)
    const suffixEnd = Math.min(text.length, end + AnchorResolver.CONTEXT_SIZE)

    const prefix = safeSlice(text, prefixStart, start)
    const quote = safeSlice(text, start, end)
    const suffix = safeSlice(text, end, suffixEnd)

    return { prefix, quote, suffix }
  }

  /**
   * Resolves an Anchor against a possibly changed document text.
   *
   * @param anchor   The stored anchor.
   * @param newText  The current document text.
   * @returns        The offset of the quote within newText, or null if not found.
   */
  static resolveAnchor(anchor: Anchor, newText: string): number | null {
    // Quick exact match of the quote
    const exactIdx = newText.indexOf(anchor.quote)
    if (exactIdx !== -1) {
      // Verify surrounding context if possible
      const before = newText.slice(Math.max(0, exactIdx - anchor.prefix.length), exactIdx)
      const after = newText.slice(exactIdx + anchor.quote.length, exactIdx + anchor.quote.length + anchor.suffix.length)

      if (before.endsWith(anchor.prefix) && after.startsWith(anchor.suffix)) {
        return exactIdx
      }
    }

    // Fallback: fuzzy search using combined context
    const pattern = `${anchor.prefix}${anchor.quote}${anchor.suffix}`
    const fuzzyIdx = newText.indexOf(pattern)
    if (fuzzyIdx !== -1) {
      return fuzzyIdx + anchor.prefix.length
    }

    return null
  }
}

/**
 * CommentEngine handles UI‑side comment creation, storage, and serialization.
 * It works with the browser's Selection API to generate anchored comments.
 */
export class CommentEngine {
  private readonly sessionId: string
  private readonly authorToken: string
  private readonly comments: Comment[] = []
  private readonly edits: Edit[] = []

  /**
   * Constructs a CommentEngine for a given session.
   *
   * @param sessionId   Identifier of the active review session.
   * @param authorToken Token representing the current user/agent.
   */
  constructor(sessionId: string, authorToken: string) {
    this.sessionId = sessionId
    this.authorToken = authorToken
  }

  /**
   * Captures the current user selection inside the document and builds an Anchor.
   *
   * @returns An Anchor describing the selection, or null if no valid selection exists.
   */
  captureSelection(): Anchor | null {
    const selection = window.getSelection()
    if (!selection || selection.isCollapsed || !selection.rangeCount) {
      return null
    }

    const range = selection.getRangeAt(0)
    const container = range.commonAncestorContainer

    // If the selection spans multiple nodes, we fallback to plain text extraction.
    let textContent = ''
    if (container.nodeType === Node.TEXT_NODE) {
      textContent = container.textContent ?? ''
    } else if (container.nodeType === Node.ELEMENT_NODE) {
      textContent = (container as Element).innerText
    } else {
      return null
    }

    const startOffset = range.startOffset
    const endOffset = range.endOffset

    // Guard against out‑of‑range offsets
    if (startOffset < 0 || endOffset > textContent.length || startOffset >= endOffset) {
      return null
    }

    try {
      return AnchorResolver.createAnchor(textContent, startOffset, endOffset)
    } catch (e) {
      console.warn('Failed to create anchor:', e)
      return null
    }
  }

  /**
   * Creates a Comment object from an Anchor and body text.
   *
   * @param anchor The anchor describing the location of the comment.
   * @param body   Markdown body of the comment.
   * @returns      A fully populated Comment instance.
   */
  createComment(anchor: Anchor, body: string): Comment {
    const now = Date.now()
    const comment: Comment = {
      id: generateUuid(),
      anchor,
      author: this.authorToken,
      body,
      createdAt: now,
    }
    this.comments.push(comment)
    return comment
  }

  /**
   * Records an Edit operation against the current document.
   *
   * @param anchor       Anchor identifying the fragment to replace.
   * @param replacement  New text that should replace the original fragment.
   * @returns            The created Edit object.
   */
  recordEdit(anchor: Anchor, replacement: string): Edit {
    const now = Date.now()
    const edit: Edit = {
      id: generateUuid(),
      anchor,
      replacement,
      author: this.authorToken,
      timestamp: now,
    }
    this.edits.push(edit)
    return edit
  }

  /**
   * Returns a shallow copy of all stored comments for the current session.
   *
   * @returns Array of Comment objects.
   */
  serializeComments(): Comment[] {
    return [...this.comments]
  }

  /**
   * Returns a shallow copy of all stored edits for the current session.
   *
   * @returns Array of Edit objects.
   */
  serializeEdits(): Edit[] {
    return [...this.edits]
  }

  /**
   * Clears all stored comments and edits after they have been flushed to the server.
   */
  clearPending(): void {
    this.comments.length = 0
    this.edits.length = 0
  }

  /**
   * Sends a comment to the ReviewServer via POST /api/session/:id/comment.
   *
   * @param comment The comment to transmit.
   * @returns       A promise that resolves when the server acknowledges receipt.
   */
  async pushComment(comment: Comment): Promise<void> {
    const url = `/api/session/${encodeURIComponent(this.sessionId)}/comment`
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-token': this.authorToken,
      },
      body: JSON.stringify(comment),
    })
    if (!response.ok) {
      const err: ApiError = await response.json()
      throw err
    }
  }

  /**
   * Sends an edit to the ReviewServer via POST /api/session/:id/edit.
   *
   * @param edit The edit to transmit.
   * @returns    A promise that resolves when the server acknowledges receipt.
   */
  async pushEdit(edit: Edit): Promise<void> {
    const url = `/api/session/${encodeURIComponent(this.sessionId)}/edit`
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-token': this.authorToken,
      },
      body: JSON.stringify(edit),
    })
    if (!response.ok) {
      const err: ApiError = await response.json()
      throw err
    }
  }

  /**
   * Flushes pending comments and edits to the server, then clears local buffers.
   *
   * @returns A promise that resolves when both comment and edit batches are sent.
   */
  async flush(): Promise<void> {
    const commentPromises = this.comments.map((c) => this.pushComment(c))
    const editPromises = this.edits.map((e) => this.pushEdit(e))
    await Promise.all([...commentPromises, ...editPromises])
    this.clearPending()
  }
}