import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, json } from "../api/client";

type AdminUser = {
  id: string; display_name: string; email: string; provider: string | null;
  provider_username: string | null; is_active: boolean; is_system_admin: boolean;
  last_login_at: string;
};

export function SystemAdminPage() {
  const client = useQueryClient();
  const users = useQuery({ queryKey: ["admin-users"], queryFn: () => api<AdminUser[]>("/admin/users") });
  const update = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Record<string, boolean> }) => api(`/admin/users/${id}`, json("PATCH", patch)),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["admin-users"] }); },
  });
  return <section><header className="page-header"><div><p className="eyebrow">System administration</p><h1>Users</h1><p>Control global administrator access and disable identities immediately.</p></div></header>
    <div className="table-card"><table><thead><tr><th>User</th><th>Provider identity</th><th>Last login</th><th>Status</th><th>System admin</th></tr></thead><tbody>{users.data?.map((user) => <tr key={user.id}><td><strong>{user.display_name}</strong><small className="block muted">{user.email}</small></td><td>{user.provider ? `${user.provider} · @${user.provider_username}` : "—"}</td><td>{new Date(user.last_login_at).toLocaleString()}</td><td><button className={user.is_active ? "secondary" : "danger"} onClick={() => update.mutate({ id: user.id, patch: { is_active: !user.is_active } })}>{user.is_active ? "Active" : "Disabled"}</button></td><td><button className="secondary" onClick={() => update.mutate({ id: user.id, patch: { is_system_admin: !user.is_system_admin } })}>{user.is_system_admin ? "Administrator" : "Standard user"}</button></td></tr>)}</tbody></table></div>
  </section>;
}
