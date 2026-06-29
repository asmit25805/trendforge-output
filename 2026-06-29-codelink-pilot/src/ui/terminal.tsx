import React, { useEffect, useRef, RefObject } from "react";
import { Terminal, ITheme } from "xterm";
import "xterm/css/xterm.css";
import { AgentAdapter } from "../agents/adapter";
import { FileChangeEvent } from "../types";

/**
 * TerminalEmulator bridges an xterm.js instance with a PTY managed by
 * {@link AgentAdapter}. It forwards user keystrokes to the PTY and renders
 * PTY output back into the terminal.
 */
export class TerminalEmulator {
  private readonly terminal: Terminal;
  private readonly adapter: AgentAdapter;

  constructor(adapter: AgentAdapter, container: HTMLElement) {
    this.adapter = adapter;
    this.terminal = new Terminal({
      cursorBlink: true,
      theme: { background: "#1e1e1e" } as ITheme
    });
    this.terminal.open(container);
    this.setupListeners();
  }

  private setupListeners(): void {
    this.terminal.onData((data) => {
      // Forward keystrokes to the PTY.
      this.adapter.sendInput("default", data);
    });
    this.adapter.onOutput((sessionId, data) => {
      this.terminal.write(data);
    });
  }

  /** Focuses the terminal input. */
  focus(): void {
    this.terminal.focus();
  }
}

/** React component that renders the terminal inside a div. */
export const TerminalComponent: React.FC<{ adapter: AgentAdapter }> = ({ adapter }) => {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      const emulator = new TerminalEmulator(adapter, containerRef.current);
      emulator.focus();
    }
  }, [adapter]);

  return <div ref={containerRef as RefObject<HTMLDivElement>} style={{ width: "100%", height: "100%" }} />;
};
