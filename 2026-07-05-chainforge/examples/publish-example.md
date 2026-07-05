# Publishing a Chain with the `chainforge` CLI

This guide walks through the end‑to‑end process of publishing a new chain definition using the `chainforge` command‑line client. Every operation is logged, retries are automatic, and a dry‑run mode lets you validate without side effects.

---

## 1. Prerequisites

| Requirement | Command |
|-------------|---------|
| Node 20+    | `node -v` (must be ≥ 20) |
| `chainforge` package | `npm install -g chainforge` |
| GitHub OAuth app (already configured in the server) | No local action required – the CLI will redirect you to GitHub for authentication. |

---

## 2. Authenticate once (session cookie is stored locally)

```bash
$ chainforge auth login
[Auth] Opening browser for GitHub OAuth…
[Auth] Received callback, validating nonce…
[Auth] JWT created, expires at 2026‑12‑31T23:59:59.000Z
[Auth] Session token saved to ~/.chainforge/session.json
```

The CLI stores the JWT in `~/.chainforge/session.json`. Subsequent commands reuse this token until it expires.

---

## 3. Prepare a chain definition file

Create a file named `my‑chain.json`. The schema matches the `ChainDefinition` type from `src/types.ts`.

```json
{
  "slug": "my-chain",
  "title": "Simple multiplier chain",
  "description": "Demonstrates a two‑step script that doubles then triples a number.",
  "status": "draft",
  "createdAt": "2026-07-05T12:00:00.000Z",
  "updatedAt": "2026-07-05T12:00:00.000Z",
  "steps": [
    {
      "id": "double",
      "type": "script",
      "payload": "return context.input * 2;",
      "inputSchema": {
        "type": "object",
        "properties": { "input": { "type": "number" } },
        "required": ["input"]
      },
      "outputSchema": { "type": "number" }
    },
    {
      "id": "triple",
      "type": "script",
      "payload": "return context.prev * 3;",
      "inputSchema": {
        "type": "object",
        "properties": { "prev": { "type": "number" } },
        "required": ["prev"]
      },
      "outputSchema": { "type": "number" }
    }
  ]
}
```

> **Tip** – Keep the file under version control; the `slug` must be globally unique in the catalog.

---

## 4. Dry‑run validation (no database writes)

```bash
$ chainforge publish --dry-run my-chain.json
[Publish] Loading definition from my-chain.json
[Publish] Fingerprint (SHA‑256): 7f3c9e2a1b4d5e6f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f
[Publish] Validation passed – no duplicate fingerprint detected.
[Publish] Dry‑run complete. No changes persisted.
```

The dry‑run confirms that the payload is syntactically correct and that the fingerprint does not clash with an existing chain.

---

## 5. Publish the chain (real write)

```bash
$ chainforge publish my-chain.json
[Publish] Loading definition from my-chain.json
[Publish] Fingerprint (SHA‑256): 7f3c9e2a1b4d5e6f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f
[RateLimiter] Checking fingerprint usage… OK
[CatalogStore] Inserting new Chain record (slug: my-chain)
[CatalogStore] Inserting ChainVersion (version: 1.0.0, checksum: 7f3c9e2a…)
[Publish] Chain published successfully.
[Publish] URL: https://chainforge.vercel.app/chain/my-chain@1.0.0
```

*What happened under the hood*:

1. **AuthManager** supplied the JWT for the request.  
2. **RateLimiter** verified that the fingerprint is within hourly/daily caps.  
3. **CatalogStore** persisted the `Chain` metadata and the immutable `ChainVersion`.  
4. The server returned the canonical URL, which is now publicly reachable.

---

## 6. Verify the published chain

```bash
$ chainforge view my-chain@1.0.0
[View] Fetching chain my-chain@1.0.0 …
[View] Title: Simple multiplier chain
[View] Description: Demonstrates a two‑step script that doubles then triples a number.
[View] Steps (2):
  • double  (script) – payload length: 24
  • triple  (script) – payload length: 24
[View] Published at: 2026‑07‑05T12:01:23.000Z
```

You can also open the URL in a browser to see the rendered catalog entry.

---

## 7. Run the newly published chain (optional)

```bash
$ chainforge run my-chain@1.0.0 '{"input":4}'
[Run] Loading chain my-chain@1.0.0 …
[Run] Executing step double … output: 8
[Run] Executing step triple … output: 24
[Run] Execution hash: a3b9c2d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2
[Run] Result written to run history (hash=a3b9c2…)
```

The CLI records the run in a local SQLite database (`~/.chainforge/run_history.db`) for later inspection.

---

## 8. Idempotency & Logging

* **Idempotent tasks** – Re‑publishing the same definition with an unchanged fingerprint results in a `409 Conflict` error; the CLI logs the conflict and exits without creating a duplicate version.
* **All side effects** – Before each write operation the CLI logs the intent (`[Publish] Inserting …`, `[Run] Executing …`). This makes the workflow fully auditable.
* **Retries** – Transient failures (e.g., network hiccups) trigger up‑to‑three exponential back‑off attempts automatically; each retry is logged (`[Publish][retry] attempt 2/3`).

---

## 9. Clean‑up (optional)

If you need to delete a draft chain locally before publishing:

```bash
$ chainforge delete my-chain --force
[Delete] Removing draft chain my-chain …
[Delete] Success – chain removed from local store.
```

*Note*: Deleting a published version is not allowed through the CLI; it requires an admin action on the server.

---

## 9. Summary checklist

- [x] Authenticate once (`chainforge auth login`).  
- [x] Write a valid `ChainDefinition` JSON file.  
- [x] Run `chainforge publish --dry-run` to validate.  
- [x] Execute `chainforge publish` to store the chain and obtain its URL.  
- [x] Use `chainforge view` to confirm the published content.  
- [x] Optionally run the chain with `chainforge run`.  

All operations are deterministic, logged, and safe to repeat. Happy chaining!