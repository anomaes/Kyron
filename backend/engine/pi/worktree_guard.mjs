import { existsSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";

function isWithin(root, candidate) {
  const pathFromRoot = relative(root, candidate);
  return pathFromRoot === "" || (
    pathFromRoot !== ".." &&
    !pathFromRoot.startsWith(`..${sep}`) &&
    !isAbsolute(pathFromRoot)
  );
}

function nearestExistingPath(candidate) {
  let current = candidate;
  while (!existsSync(current)) {
    const parent = dirname(current);
    if (parent === current) return current;
    current = parent;
  }
  return current;
}

function writeTarget(inputPath, cwd) {
  const normalized = inputPath.startsWith("@") ? inputPath.slice(1) : inputPath;
  const lexicalTarget = resolve(cwd, normalized);
  const existingPath = nearestExistingPath(lexicalTarget);
  return {
    lexicalTarget,
    resolvedExistingPath: realpathSync(existingPath),
  };
}

export default function worktreeGuard(pi) {
  const worktree = realpathSync(process.cwd());

  pi.on("tool_call", (event) => {
    if (event.toolName !== "write" && event.toolName !== "edit") return undefined;

    const inputPath = event.input?.path;
    if (typeof inputPath !== "string" || inputPath.length === 0) {
      return { block: true, reason: "A non-empty worktree path is required" };
    }

    let target;
    try {
      target = writeTarget(inputPath, worktree);
    } catch (error) {
      return {
        block: true,
        reason: `Could not validate write path ${JSON.stringify(inputPath)}: ${String(error)}`,
      };
    }

    if (
      !isWithin(worktree, target.lexicalTarget) ||
      !isWithin(worktree, target.resolvedExistingPath)
    ) {
      return {
        block: true,
        reason: `Pi may only modify files in the current run worktree: ${inputPath}`,
      };
    }

    return undefined;
  });
}
