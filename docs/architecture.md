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

Each run has one branch and worktree created from an exact fetched SHA. Root and
transitive workflow JSON are read with `git show <sha>:<path>` and stored as a
secret-free snapshot. All invocations share the run worktree. Process nodes can
run concurrently only within a checkpointed wave; control nodes are serialized.

Prompt nodes add a process-local filesystem boundary around Pi. Bubblewrap presents a
recursively read-only view of the backend container and rebinds only the resolved run
worktree and ephemeral Pi state read-write. Pi and every child process share that mount
view and a private PID namespace. Bash and Script nodes retain direct backend-container
execution.

Workflow tags are versioned metadata inside those JSON definitions rather than
database state. Consequently catalog grouping, filtering, and builder child-workflow
selection always describe the same default-branch revision returned by the workflow
API. Tags have no execution semantics.

The run graph is reconstructed from the immutable workflow bundle plus durable
invocation and node-execution rows. The root graph and each child invocation are
rendered as separate instances; parent execution IDs establish invocation edges and
loop iteration numbers order review rounds. No visualization-only execution state is
persisted.

Secret values occupy a separate lifetime from public workflow context. Stored
Fernet ciphertext is decrypted immediately before process or code-host use, added
to an in-memory redactor, and discarded after the operation. Secret values are
never valid `${...}` template variables.

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
