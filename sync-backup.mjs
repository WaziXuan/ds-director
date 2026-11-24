import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const ONE_DRIVE = process.env.OneDrive || process.env.OneDriveConsumer;
if (!ONE_DRIVE && !process.argv[2]) {
  throw new Error("Set OneDrive/OneDriveConsumer or pass an explicit destination directory.");
}

export const DEFAULT_DEST = ONE_DRIVE
  ? path.join(ONE_DRIVE, "文档", "SOMEFILE", "ds-director")
  : "";
const DEST_BASE = process.argv[2] ? path.resolve(process.argv[2]) : DEFAULT_DEST;
const DEST = path.join(DEST_BASE, path.basename(ROOT));
const SKIP = new Set([".git", ".venv", ".dsd", "__pycache__", ".pytest_cache", ".mypy_cache",
  "node_modules", "build", "dist", "tmp"]);

async function hash(file) {
  return createHash("sha256").update(await fs.readFile(file)).digest("hex");
}

async function* files(dir) {
  for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
    if (SKIP.has(entry.name) || entry.name.endsWith(".egg-info")) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* files(full);
    else if (entry.isFile()) yield full;
  }
}

let copied = 0;
let unchanged = 0;
for await (const source of files(ROOT)) {
  const relative = path.relative(ROOT, source);
  const destination = path.join(DEST, relative);
  await fs.mkdir(path.dirname(destination), { recursive: true });
  const sourceHash = await hash(source);
  let destinationHash = "";
  try {
    destinationHash = await hash(destination);
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  if (sourceHash === destinationHash) {
    unchanged += 1;
    continue;
  }
  const temporary = destination + ".tmp";
  await fs.copyFile(source, temporary);
  if (await hash(temporary) !== sourceHash) {
    throw new Error(`Hash verification failed: ${relative}`);
  }
  await fs.rename(temporary, destination);
  copied += 1;
}
console.log(`Backup: ${copied} copied, ${unchanged} unchanged, destination: ${DEST}`);
