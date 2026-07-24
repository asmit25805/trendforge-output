# Basic Example

## Prompt Metadata (`meta.json`)

```json
{
  "id": "basic-example",
  "title": "Basic Example Prompt",
  "description": "A minimal prompt that generates a simple counter component using React and Tailwind.",
  "tags": ["basic", "counter", "react"],
  "previewImage": "preview.png",
  "author": "asmit25805",
  "sourceUrl": "https://github.com/asmit25805/prompt-lab"
}
```

## Prompt Markdown (`prompt.md`)

```markdown
# Counter Prompt

Create a React component that displays a button and a counter. Each click on the button increments the counter. Use Tailwind for styling.

**Requirements**
- Use functional components and hooks.
- Export the component as the default export.
- Keep the component self‑contained; additional CSS can be added in a separate file if needed.
```

## How the Playground Renders the Prompt

When the user selects this prompt, the following flow occurs:

1. **PromptStore** loads `meta.json` and `prompt.md` and caches the metadata.
2. **PlaygroundEngine** receives a `PromptEdit` containing the edited markdown.
3. **AIClient** sends the markdown to the configured LLM and receives a `GeneratedCode` payload.
4. **SandboxCompiler** bundles the generated TypeScript/React files with esbuild inside a WebWorker.
5. The bundle is injected into an isolated iframe; any runtime errors are captured and streamed back as a `PreviewResult`.
6. The UI displays the live preview alongside any compilation or runtime errors.

### Example Zod Schema for Validation

```ts
import { z } from "zod";

export const PromptMetaSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string(),
  tags: z.array(z.string()),
  previewImage: z.string(),
  author: z.string().optional(),
  sourceUrl: z.string().optional(),
});
```

### Fetching Prompt Metadata with React Query

```tsx
import { useQuery } from "@tanstack/react-query";
import { PromptMeta } from "../types";

export function usePromptMeta(id: string) {
  return useQuery<PromptMeta>(["promptMeta", id], async () => {
    const response = await fetch(`/prompts/${id}/meta.json`);
    if (!response.ok) {
      throw new Error(`Failed to load meta for ${id}`);
    }
    return response.json();
  });
}
```

### Generated Counter Component (Result of the AI Generation)

```tsx
import React, { useState } from "react";

export default function Counter() {
  const [count, setCount] = useState(0);

  return (
    <div className="flex flex-col items-center p-4">
      <button
        className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700"
        onClick={() => setCount((c) => c + 1)}
      >
        Increment
      </button>
      <p className="mt-2 text-lg">Count: {count}</p>
    </div>
  );
}
```

### Tailwind Styling

The component uses Tailwind utility classes directly in the JSX. If additional styles are required, they can be placed in a separate `styles.css` file and imported by the generated code.

### Live Preview

The compiled bundle is served as a blob URL (`iframeUrl`) and rendered inside an isolated iframe. Any console errors that occur during execution are collected in `runtimeErrors` and displayed in a collapsible error panel, ensuring the host page remains stable.

---  

This example demonstrates the full round‑trip from static prompt files to a live, interactive preview powered entirely in the browser.