import { useState, useEffect, useCallback, createContext, useContext, ReactNode } from "react";
import { useQuery, useMutation, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { z } from "zod";
import init, { EditorFacade as WasmEditorFacade } from "../pkg/rope_meld"; // Adjust path as needed

/**
 * Represents an edit coming from the UI.
 * - Insert: requires `pos` and `text`.
 * - Delete: requires `range` as a tuple `[start, end]`.
 */
export interface JsEdit {
  kind: "insert" | "delete";
  /** Zero‑based character position for insert operations */
  pos?: number;
  /** Text to insert */
  text?: string;
  /** Range to delete (inclusive start, exclusive end) */
  range?: [number, number];
}

/**
 * Read‑only snapshot of the document returned to the UI.
 */
export interface JsSnapshot {
  /** Full markdown content */
  markdown: string;
  /** Optional metadata such as version vector */
  version?: Record<string, number>;
}

/**
 * High‑level façade exposing the core engine to React components.
 * It lazily loads the WebAssembly module and forwards calls to the
 * underlying `EditorFacade` implementation.
 */
export class EditorFacade {
  private wasmFacade: WasmEditorFacade | null = null;

  constructor() {
    this.initialize();
  }

  private async initialize() {
    await init(); // Initialise the WASM module
    this.wasmFacade = new WasmEditorFacade();
  }

  /** Apply an edit coming from the UI. */
  async applyEdit(edit: JsEdit): Promise<void> {
    if (!this.wasmFacade) {
      await this.initialize();
    }
    // Validation using zod
    const editSchema = z.object({
      kind: z.enum(["insert", "delete"]),
      pos: z.number().int().nonnegative().optional(),
      text: z.string().optional(),
      range: z.tuple([z.number().int().nonnegative(), z.number().int().nonnegative()]).optional()
    });
    const parsed = editSchema.parse(edit);

    if (parsed.kind === "insert") {
      this.wasmFacade!.apply_insert(parsed.pos!, parsed.text!);
    } else {
      const [start, end] = parsed.range!;
      this.wasmFacade!.apply_delete(start, end);
    }
  }

  /** Retrieve the current markdown snapshot. */
  async getSnapshot(): Promise<JsSnapshot> {
    if (!this.wasmFacade) {
      await this.initialize();
    }
    const markdown = this.wasmFacade!.get_markdown();
    const versionJson = this.wasmFacade!.get_version_vector();
    const version = JSON.parse(versionJson);
    return { markdown, version };
  }
}

/**
 * React hook that provides a ready‑to‑use `EditorFacade` instance.
 */
export function useEditorFacade(): EditorFacade {
  const [facade] = useState(() => new EditorFacade());
  return facade;
}
