import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, json } from "../api/client";
import { PiModelsAdminPanel } from "../components/PiModelsAdminPanel";

type AdminUser = {
  id: string; display_name: string; email: string; provider: string | null;
  provider_username: string | null; is_active: boolean; is_system_admin: boolean;
  last_login_at: string;
};

export function SystemAdminPage() {
  const [section, setSection] = useState<"providers" | "users">("providers");
  return <section><header className="page-header"><div><p className="eyebrow">System administration</p><h1>Administration</h1><p>Manage global AI routing and trusted Kyron identities.</p></div></header><div className="admin-tabs" role="tablist" aria-label="Administration sections"><button role="tab" aria-selected={section === "providers"} className={section === "providers" ? "active" : ""} onClick={() => setSection("providers")}>AI providers</button><button role="tab" aria-selected={section === "users"} className={section === "users" ? "active" : ""} onClick={() => setSection("users")}>Users</button></div>{section === "providers" ? <PiModelsAdminPanel /> : <UsersAdminPanel />}</section>;
}

function UsersAdminPanel() {
  const client = useQueryClient();
  const users = useQuery({ queryKey: ["admin-users"], queryFn: () => api<AdminUser[]>("/admin/users") });
  const update = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Record<string, boolean> }) => api(`/admin/users/${id}`, json("PATCH", patch)),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["admin-users"] }); },
  });
  return <div className="table-card"><table><thead><tr><th>User</th><th>Provider identity</th><th>Last login</th><th>Status</th><th>System admin</th></tr></thead><tbody>{users.data?.map((user) => <tr key={user.id}><td><strong>{user.display_name}</strong><small className="block muted">{user.email}</small></td><td>{user.provider ? `${user.provider} · @${user.provider_username}` : "—"}</td><td>{new Date(user.last_login_at).toLocaleString()}</td><td><button className={user.is_active ? "secondary" : "danger"} onClick={() => update.mutate({ id: user.id, patch: { is_active: !user.is_active } })}>{user.is_active ? "Active" : "Disabled"}</button></td><td><button className="secondary" onClick={() => update.mutate({ id: user.id, patch: { is_system_admin: !user.is_system_admin } })}>{user.is_system_admin ? "Administrator" : "Standard user"}</button></td></tr>)}</tbody></table></div>;
}
