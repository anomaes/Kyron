# Architecture

Kyron is a single-VM system with Caddy as the only exposed service. Caddy serves
the React bundle, delegates browser identity to the code-host OAuth service, and
forwards authenticated API/WebSocket traffic to one FastAPI worker. PostgreSQL
is the durable source of execution truth; repository clones, worktrees, process
output, and artifacts live on a persistent host volume.

The backend separates API orchestration from domain services and integrations.
The in-process coordinator owns a bounded run semaphore plus task and process
registries. Each run is recoverable because mutable in-memory scheduling state
is reflected in run, invocation, wave, execution, attempt, edge-evaluation, and
log rows. Startup marks in-flight work interrupted and leaves feedback waits
unchanged.

Each run starts with a root branch and worktree created from an exact fetched
SHA. Root and transitive workflow YAML is read with `git show <sha>:<path>` and
stored as a secret-free snapshot. Shared invocations reference the nearest
owning workspace. Isolated invocations fork a child branch and worktree from the
parent's exact clean checkpoint; isolated-parallel siblings can execute
concurrently without sharing mutable filesystem, Git staging, or rollback
state.

The code subject and executable workflow bundle have independent pinned
revisions. Delivery runs normally select the same revision for both.
Report-only runs use a branch or change-request source commit as the subject and
load workflow definitions and credential policy from the trusted project
default branch or an authorized local snapshot. Their workspaces remain local,
and terminal evidence records both revisions.

An isolated parallel batch freezes its parent workspace until every required
member succeeds or the batch fails. Successful child heads are merged into the
parent with explicit merge commits in stable parent node-ID order. The complete
merge sequence is atomic from the scheduler's perspective: a conflict resets
and cleans the parent back to the batch base before failure is recorded. Child
outputs become visible to the parent only after that integration succeeds.
Process nodes inside any one invocation may still run concurrently within a
checkpointed wave and share that invocation's workspace.

Prompt nodes add a process-local filesystem boundary around Pi. Bubblewrap presents a
recursively read-only view of the backend container and rebinds only the resolved run
worktree and ephemeral Pi state read-write. Pi and every child process share that mount
view and a private PID namespace. Bash and Script nodes retain direct backend-container
execution.

Workflow tags are versioned metadata inside those YAML definitions rather than
database state. Consequently catalog grouping, filtering, and builder child-workflow
selection always describe the same default-branch revision returned by the workflow
API. Tags have no execution semantics.

The run graph is reconstructed from the immutable workflow bundle plus durable
invocation, workspace, batch, gate, and node-execution rows. The root graph and
each child invocation are rendered as separate instances; parent execution IDs
establish invocation edges and loop iteration numbers order review rounds. No
visualization-only execution state is persisted.

Secret values occupy a separate lifetime from public workflow context. Stored
Fernet ciphertext is decrypted immediately before process or code-host use, added
to an in-memory redactor, and discarded after the operation. Secret values are
never valid `${...}` template variables.

System administrators manage a versioned, secret-free Pi provider registry. Saving or
restoring a revision requires validation by the installed Pi runtime and produces an
authorization audit event. Each run snapshots the active provider document and revision
identifier when it is queued; retries and review iterations therefore retain the same
endpoint routing. Provider documents contain only credential-variable references. Their
values continue to come from the triggering user's encrypted credential store.

GitLab and GitHub integrations implement one normalized code-host contract. A
session carries one provider identity, projects carry one provider, and API
boundaries reject cross-provider mutations. Provider-specific REST payloads and
webhook shapes are normalized before they reach orchestration services. The full
contract, migration rules, and acceptance criteria are defined in
`docs/code-host-provider-spec.md`.

Authorization uses a global system-administrator flag plus project memberships. Each
membership may hold multiple built-in or custom project roles; roles contain fixed,
server-recognized permission keys. All project API and WebSocket reads require membership
and all mutations require their operation-specific permission.

Approval policies are project database state referenced by stable keys from workflow
definitions. An opened gate snapshots the resolved policy and provider identities so later
membership changes cannot rewrite an in-flight decision boundary. Gate decisions and
authorization audit events are append-only. Run reports combine this state with durable
invocation paths, so child-workflow gates retain their execution hierarchy.

Every isolated workspace owns at most one open workspace-review request. Its
source is the child branch and its target is the immediate parent branch. Gates
link directly to that request and workspace, so approvals and revision comments
advance only the addressed child even when sibling gates are open. The root
final request is a separate record targeting the configured base ref; only its
merge or close triggers whole-run resource cleanup.
