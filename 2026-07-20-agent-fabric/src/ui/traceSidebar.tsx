// src/ui/traceSidebar.tsx
import React, { useEffect, useState } from "react";
import { RPCChannel } from "../rpc/channel";
import { RPCMessage, RPCMessageType, TraceEvent, COMMON_PROPERTIES } from "../types";

/**
 * Props for the TraceSidebar component.
 */
interface TraceSidebarProps {
  /** RPC channel used to receive trace events */
  rpc: RPCChannel;
}

/**
 * Simple sidebar that displays trace events received from the engine.
 */
export const TraceSidebar: React.FC<TraceSidebarProps> = ({ rpc }) => {
  const [events, setEvents] = useState<TraceEvent[]>([]);

  useEffect(() => {
    const handler = (msg: RPCMessage) => {
      if (msg.type === RPCMessageType.EVENT) {
        setEvents((prev) => [...prev, msg.payload as TraceEvent]);
      }
    };
    rpc.on("message", handler);
    return () => {
      rpc.off("message", handler);
    };
  }, [rpc]);

  return (
    <div style={{ padding: "0.5rem", overflowY: "auto", maxHeight: "100%" }}>
      <h3>Trace Events</h3>
      <ul>
        {events.map((e, i) => (
          <li key={i}>
            [{new Date(e.timestamp).toLocaleTimeString()}] {e.event}
            {e.data ? ": " + JSON.stringify(e.data) : null}
          </li>
        ))}
      </ul>
    </div>
  );
};
