const relativePaths = new WeakMap<File, string>()
const ignoredParts = new Set([
  ".git",
  ".venv",
  "venv",
  "node_modules",
  "__pycache__",
  ".cache",
  ".nexaflow",
  "__MACOSX",
  ".DS_Store",
])

export function agentUploadPath(file: File) {
  return relativePaths.get(file) || file.webkitRelativePath || file.name
}

export function isTextOnlyUpload(path: string, size: number) {
  return (
    size > 5 * 1024 * 1024 &&
    !path.includes("/") &&
    !path.toLowerCase().endsWith(".zip")
  )
}

export function isAgentUploadFile(file: File) {
  return !agentUploadPath(file)
    .split("/")
    .some((part) => ignoredParts.has(part))
}

export function agentUploadForm(files: File[]) {
  const body = new FormData()
  files.forEach((file) => body.append("files", file, agentUploadPath(file)))
  return body
}

export async function droppedAgentFiles(
  dataTransfer: DataTransfer
): Promise<File[]> {
  const items = Array.from(dataTransfer.items ?? []).filter(
    (item) => item.kind === "file"
  )
  const entries = items
    .map((item) => item.webkitGetAsEntry?.())
    .filter((entry): entry is FileSystemEntry => !!entry)
  if (!entries.length) {
    const files = Array.from(dataTransfer.files)
    return (
      files.length
        ? files
        : items
            .map((item) => item.getAsFile())
            .filter((file): file is File => file !== null)
    ).filter(isAgentUploadFile)
  }
  const files: File[] = []
  async function read(entry: FileSystemEntry, parent = "") {
    if (ignoredParts.has(entry.name)) return
    const path = parent + entry.name
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) =>
        (entry as FileSystemFileEntry).file(resolve, reject)
      )
      relativePaths.set(file, path)
      files.push(file)
      return
    }
    const reader = (entry as FileSystemDirectoryEntry).createReader()
    let children: FileSystemEntry[]
    do {
      children = await new Promise<FileSystemEntry[]>((resolve, reject) =>
        reader.readEntries(resolve, reject)
      )
      for (const child of children) await read(child, path + "/")
    } while (children.length)
  }
  for (const entry of entries) await read(entry)
  return files
}
