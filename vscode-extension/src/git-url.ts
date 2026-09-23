export type RepositoryIdentity = {
  host: string;
  path: string;
};

export function repositoryIdentity(rawUrl: string): RepositoryIdentity | undefined {
  const scpLike = rawUrl.match(/^(?:[^@/]+@)?([^:/]+):(.+)$/);
  if (scpLike?.[1] && scpLike[2] && !rawUrl.includes("://")) {
    return { host: scpLike[1].toLowerCase(), path: normalizeRepositoryPath(scpLike[2]) };
  }
  try {
    const url = new URL(rawUrl);
    if (!url.hostname) return undefined;
    return { host: url.host.toLowerCase(), path: normalizeRepositoryPath(url.pathname) };
  } catch {
    return undefined;
  }
}

export function normalizeRepositoryPath(value: string): string {
  let path = value.trim().replace(/^\/+/, "").replace(/\/+$/, "");
  if (path.toLowerCase().endsWith(".git")) {
    path = path.slice(0, -4);
  }
  try {
    return decodeURIComponent(path).toLowerCase();
  } catch {
    return path.toLowerCase();
  }
}
