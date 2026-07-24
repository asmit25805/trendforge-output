# Prompt Lab

Prompt Lab is an in‑browser playground that turns prompt metadata into instantly runnable React + Tailwind previews. It loads prompt definitions from the repository, sends edited markdown to a configurable language‑model provider, validates the generated code, bundles it securely, and streams a live preview back to the UI. All processing happens client‑side, keeping user code isolated while delivering near‑zero latency feedback.

## Features
- **Live preview** – Edit a prompt markdown file and see the compiled React component update instantly.
- **Secure sandbox** – Bundling runs in a WebWorker, execution occurs in an isolated iframe, preventing any runtime side‑effects from escaping the sandbox.
- **Pluggable providers** – The `AIClient` abstraction supports OpenAI, Claude, and can be extended to other services.

## Installation
```bash
npm install prompt-lab
```

## Quick Start
```bash
npx prompt-lab list            # List all available prompts
npx prompt-lab generate basic # Generate code for the "basic" prompt
npx prompt-lab preview basic   # Bundle and preview the generated code
```

## API Reference
### Types
- **PromptMeta** – Metadata describing a prompt (id, title, description, tags, etc.).
- **PromptEdit** – Editable markdown content for a prompt.
- **GeneratedCode** – Result of the generation step containing the source code and its temporary path.
- **Bundle** – The bundled JavaScript produced by the compiler.
- **PreviewResult** – Information required to display the live preview (URL).
- **GenerationOptions** – Options passed to the client when generating code.

### Classes
- **PromptStore** – Loads, validates, and caches prompt metadata and markdown files.
- **AIClient** – Sends prompt edits to a language‑model provider and receives generated code.
- **PlaygroundEngine** – Orchestrates validation, generation, bundling, and preview.
- **SandboxCompiler** – Bundles generated code with esbuild and provides a preview URL.

## Architecture
```mermaid
flowchart TD
    A[User edits prompt.md] --> B[PromptStore validates & caches]
    B --> C[AIClient generates TypeScript/React code]
    C --> D[SandboxCompiler bundles with esbuild]
    D --> E[PreviewResult (iframe URL)]
    E --> F[UI displays live preview]
```

The diagram above illustrates the data flow from user edits to the live preview. All heavy‑lifting (generation and bundling) occurs in isolated environments to maintain security.
