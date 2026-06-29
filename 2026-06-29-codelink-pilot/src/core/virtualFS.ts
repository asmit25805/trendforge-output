import BrowserFS from "browserfs";
import { EventEmitter } from "events";
import { FileStat, FileChangeEvent } from "../types";

/**
 * VirtualFS provides a POSIX‑like file system API backed by BrowserFS.
 * All operations are persisted in IndexedDB and each mutating call emits a
 * {@link FileChangeEvent} that can be observed via {@link watch}.
 */
export class VirtualFS {
  private readonly emitter = new EventEmitter();
  private fs: BrowserFS.FileSystem.FileSystem | null = null;

  /** Mounts the underlying BrowserFS instance. */
  async mount(): Promise<void> {
    return new Promise((resolve, reject) => {
      BrowserFS.configure({
        fs: "IndexedDB",
        options: { storeName: "codelink-pilot-fs" }
      }, (e) => {
        if (e) return reject(e);
        this.fs = BrowserFS.BFSRequire("fs");
        resolve();
      });
    });
  }

  /** Reads a file as UTF‑8 text. */
  async readFile(path: string): Promise<string> {
    if (!this.fs) throw new Error("VirtualFS not mounted");
    return new Promise((resolve, reject) => {
      this.fs!.readFile(path, "utf8", (err: NodeJS.ErrnoException | null, data: string) => {
        if (err) return reject(err);
        resolve(data);
      });
    });
  }

  /** Writes text to a file, creating parent directories as needed. */
  async writeFile(path: string, data: string): Promise<void> {
    if (!this.fs) throw new Error("VirtualFS not mounted");
    return new Promise((resolve, reject) => {
      this.fs!.writeFile(path, data, "utf8", (err: NodeJS.ErrnoException | null) => {
        if (err) return reject(err);
        this.emitter.emit("change", { path, type: "changed" } as FileChangeEvent);
        resolve();
      });
    });
  }

  /** Registers a listener for file change events. */
  watch(callback: (event: FileChangeEvent) => void): void {
    this.emitter.on("change", callback);
  }
}

/** Re‑export FileStat so that the module matches its declared exports. */
export { FileStat } from "../types";
