import assert from "node:assert/strict";
import test from "node:test";

import { repositoryIdentity } from "./git-url";

test("repositoryIdentity normalizes HTTPS and SCP-style Git remotes", () => {
  assert.deepEqual(repositoryIdentity("https://GitHub.com/Example/Kyron.git"), {
    host: "github.com",
    path: "example/kyron",
  });
  assert.deepEqual(repositoryIdentity("git@gitlab.example.internal:Team/Kyron.git"), {
    host: "gitlab.example.internal",
    path: "team/kyron",
  });
});

test("repositoryIdentity decodes paths and rejects invalid URLs", () => {
  assert.deepEqual(repositoryIdentity("https://example.test/team%20name/repo"), {
    host: "example.test",
    path: "team name/repo",
  });
  assert.equal(repositoryIdentity("not a remote"), undefined);
});
