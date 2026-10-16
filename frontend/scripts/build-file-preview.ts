import { cp, mkdir, rm } from "node:fs/promises"
import { fileURLToPath } from "node:url"
import path from "node:path"

const root = fileURLToPath(new URL("../", import.meta.url))
const output = path.join(root, "public/file-preview")
await rm(output, { recursive: true, force: true })
await mkdir(output, { recursive: true })
const result = await Bun.build({
  entrypoints: [
    path.join(
      root,
      "src/components/agents/artifacts/preview-runtime/viewer.ts"
    ),
  ],
  outdir: output,
  target: "browser",
  format: "esm",
  splitting: true,
  minify: true,
  naming: {
    entry: "viewer.js",
    chunk: "[name]-[hash].[ext]",
    asset: "[name]-[hash].[ext]",
  },
})
if (!result.success)
  throw new AggregateError(result.logs, "File preview build failed")
const pdf = path.join(root, "node_modules/pdfjs-dist")
// Classic workers work inside an opaque sandbox in browsers where module
// workers cannot inherit the blob creator's opaque origin.
const worker = await Bun.build({
  entrypoints: [path.join(pdf, "build/pdf.worker.mjs")],
  outdir: output,
  target: "browser",
  format: "iife",
  define: { "import.meta.url": "self.location.href" },
  minify: true,
  naming: "pdf.worker.js",
})
if (!worker.success)
  throw new AggregateError(worker.logs, "PDF worker build failed")
for (const directory of ["cmaps", "standard_fonts", "wasm"]) {
  await cp(path.join(pdf, directory), path.join(output, directory), {
    recursive: true,
  })
}
// Preserve the licenses shipped with the distributed viewer dependencies.
for (const name of ["docx-preview", "exceljs", "pdfjs-dist", "pptx-preview"]) {
  const files = new Bun.Glob("{LICENSE*,LICENCE*}")
  for await (const license of files.scan(
    path.join(root, "node_modules", name)
  )) {
    await cp(
      path.join(root, "node_modules", name, license),
      path.join(output, `${name}-${license}`)
    )
  }
}
