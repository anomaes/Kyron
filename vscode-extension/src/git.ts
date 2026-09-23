import * as vscode from "vscode";
import { normalizeRepositoryPath, repositoryIdentity } from "./git-url";
import type { Project } from "./types";

export { repositoryIdentity } from "./git-url";

type GitRemote = {
  name: string;
  fetchUrl?: string;
  pushUrl?: string;
};

type GitRepository = {
  rootUri: vscode.Uri;
  state: {
    HEAD?: { name?: string };
    remotes: GitRemote[];
  };
};

type GitApi = {
  repositories: GitRepository[];
  getRepository(uri: vscode.Uri): GitRepository | null;
};

type GitExtension = {
  enabled: boolean;
  getAPI(version: 1): GitApi;
};

export async function workspaceRepository(): Promise<GitRepository | undefined> {
  const extension = vscode.extensions.getExtension<GitExtension>("vscode.git");
  if (!extension) {
    return undefined;
  }
  const exports = extension.isActive ? extension.exports : await extension.activate();
  if (!exports.enabled) {
    return undefined;
  }
  const api = exports.getAPI(1);
  const activeUri = vscode.window.activeTextEditor?.document.uri;
  return (activeUri ? api.getRepository(activeUri) : null) ?? api.repositories[0];
}

export async function matchWorkspaceProject(projects: Project[]): Promise<Project | undefined> {
  const repository = await workspaceRepository();
  if (!repository) {
    return undefined;
  }
  const remotes = [...repository.state.remotes].sort((left, right) => {
    if (left.name === "origin") return -1;
    if (right.name === "origin") return 1;
    return left.name.localeCompare(right.name);
  });
  for (const remote of remotes) {
    for (const rawUrl of [remote.fetchUrl, remote.pushUrl]) {
      if (!rawUrl) continue;
      const identity = repositoryIdentity(rawUrl);
      if (!identity) continue;
      const match = projects.find((project) => {
        const projectIdentity = repositoryIdentity(project.git_url);
        const projectPath = normalizeRepositoryPath(project.provider_project_path);
        return (
          projectIdentity?.host === identity.host &&
          (projectIdentity.path === identity.path || projectPath === identity.path)
        );
      });
      if (match) return match;
    }
  }
  return undefined;
}

export async function currentBranch(): Promise<string | undefined> {
  return (await workspaceRepository())?.state.HEAD?.name;
}
