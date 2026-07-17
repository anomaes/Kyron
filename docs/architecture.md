# Architecture

Kyron is a single-VM system with Caddy as the only exposed service. Caddy serves
the React bundle, delegates browser identity to the GitLab OAuth service, and
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

Secret values occupy a separate lifetime from public workflow context. Stored
Fernet ciphertext is decrypted immediately before process or GitLab use, added
to an in-memory redactor, and discarded after the operation. Secret values are
never valid `${...}` template variables.

