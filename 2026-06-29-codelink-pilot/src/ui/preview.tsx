import React, { useEffect, useState } from "react";
import { EventEmitter } from "events";
import { VirtualFS } from "../core/virtualFS";
import { FileChangeEvent, PreviewResult, Config } from "../types";
import { marked } from "marked";

/**
 * PreviewEngine renders files from the virtual filesystem into HTML or React
 * nodes. It supports Markdown, HTML, and image assets.
 */
export class PreviewEngine {
  private readonly vfs: VirtualFS;
  private readonly emitter = new EventEmitter();

  constructor(vfs: VirtualFS) {
    this.vfs = vfs;
  }

  /** Renders a file and returns a {@link PreviewResult}. */
  async render(path: string): Promise<PreviewResult> {
    const ext = path.split(".").pop()?.toLowerCase();
    const content = await this.vfs.readFile(path);
    let html = "";
    if (ext === "md") {
      html = marked(content);
    } else if (ext === "html" || ext === "htm") {
      html = content;
    } else {
      // For unsupported types, wrap the raw content in a <pre> block.
      html = `<pre>${content}</pre>`;
    }
    return { html };
  }

  /** Emits an event when a previewable file changes. */
  watch(callback: (event: FileChangeEvent) => void): void {
    this.emitter.on("change", callback);
  }
}

/** React component that displays the rendered preview of a given file path. */
export const PreviewComponent: React.FC<{ vfs: VirtualFS; path: string }> = ({ vfs, path }) => {
  const [html, setHtml] = useState<string>("");

  useEffect(() => {
    const engine = new PreviewEngine(vfs);
    const load = async () => {
      const result = await engine.render(path);
      setHtml(result.html);
    };
    load();
    const handleChange = (event: FileChangeEvent) => {
      if (event.path === path) load();
    };
    engine.watch(handleChange);
    return () => {
      // Cleanup listeners if needed.
    };
  }, [vfs, path]);

  return <div dangerouslySetInnerHTML={{ __html: html }} />;
};
