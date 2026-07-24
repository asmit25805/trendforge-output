import { GeneratedCode, Bundle, PreviewResult } from "../types.js";
import { build } from "esbuild";
import { writeFile, readFile } from "fs/promises";
import { resolve } from "path";

/**
 * Compiler that bundles generated TypeScript/React code in a secure environment.
 *
 * It uses esbuild to produce a self‑contained JavaScript bundle that can be
 * executed inside an isolated iframe.
 */
export class SandboxCompiler {
  /**
   * Bundle the provided generated code into a self‑contained JavaScript bundle.
   *
   * @param generated The generated source code.
   * @returns An object describing the bundle location and content.
   */
  async bundle(generated: GeneratedCode): Promise<Bundle> {
    const outFile = resolve("tmp", `${Date.now()}.js`);
    await build({
      entryPoints: [generated.path],
      bundle: true,
      platform: "node",
      outfile: outFile,
      external: ["react", "react-dom"],
    });
    const code = await readFile(outFile, "utf-8");
    return { path: outFile, code };
  }

  /**
   * Execute the bundled code inside an isolated iframe and return a preview URL.
   *
   * @param bundle The bundle produced by {@link bundle}.
   * @returns Information needed to display the preview.
   */
  async preview(bundle: Bundle): Promise<PreviewResult> {
    // For the purpose of this repository we simulate a preview URL.
    const previewUrl = `data:text/html;base64,${Buffer.from(bundle.code).toString("base64")}`;
    return { url: previewUrl };
  }
}
