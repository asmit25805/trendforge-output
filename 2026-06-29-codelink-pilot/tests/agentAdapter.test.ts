import { AgentAdapter } from "../src/agents/adapter";
import { VirtualFS } from "../src/core/virtualFS";
import { SessionOptions, AgentSession, FileChangeEvent, Config } from "../src/types";

describe("AgentAdapter", () => {
  let vfs: VirtualFS;
  let adapter: AgentAdapter;

  beforeEach(async () => {
    vfs = new VirtualFS();
    await vfs.mount();
    adapter = new AgentAdapter(vfs);
  });

  test("starts a session and emits output", async () => {
    const session = await adapter.startSession();
    expect(session).toHaveProperty("id");
    expect(session.id).toMatch(/^session-\d+$/);

    const outputPromise = new Promise<string>((resolve) => {
      adapter.onOutput((sessionId, data) => {
        if (sessionId === session.id) resolve(data);
      });
    });

    await adapter.sendInput(session.id, "echo hello\n");
    const output = await outputPromise;
    expect(output).toContain("hello");
  });
});
