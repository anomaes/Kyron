import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { User } from "../types";

export function AppShell() {
  const user = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me") });
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">K</span>
          <div><strong>Kyron</strong><small>Workflow Engine</small></div>
        </div>
        <nav>
          <NavLink to="/projects">Projects</NavLink>
          <NavLink to="/runs">Runs</NavLink>
          <NavLink to="/credentials">Credentials</NavLink>
        </nav>
        <div className="trust-note">Trusted internal execution</div>
        <div className="user-card">
          {user.data?.avatar_url ? <img src={user.data.avatar_url} alt="" /> : <span className="avatar">{user.data?.display_name?.[0] ?? "?"}</span>}
          <div><strong>{user.data?.display_name ?? "Loading…"}</strong><small>@{user.data?.gitlab_username ?? ""}</small></div>
        </div>
      </aside>
      <main className="main"><Outlet context={{ user: user.data }} /></main>
    </div>
  );
}
