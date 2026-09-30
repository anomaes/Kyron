import { lazy } from "react";
import { Navigate, Route, Routes } from "react-router";
import { AppShell } from "./components/AppShell";

const CredentialsPage = lazy(() => import("./pages/CredentialsPage").then((m) => ({ default: m.CredentialsPage })));
const ProjectsPage = lazy(() => import("./pages/ProjectsPage").then((m) => ({ default: m.ProjectsPage })));
const RunDetailPage = lazy(() => import("./pages/RunDetailPage").then((m) => ({ default: m.RunDetailPage })));
const RunsPage = lazy(() => import("./pages/RunsPage").then((m) => ({ default: m.RunsPage })));
const WorkflowBuilderPage = lazy(() => import("./pages/WorkflowBuilderPage").then((m) => ({ default: m.WorkflowBuilderPage })));
const WorkflowListPage = lazy(() => import("./pages/WorkflowListPage").then((m) => ({ default: m.WorkflowListPage })));
const ProjectAdminPage = lazy(() => import("./pages/ProjectAdminPage").then((m) => ({ default: m.ProjectAdminPage })));
const SystemAdminPage = lazy(() => import("./pages/SystemAdminPage").then((m) => ({ default: m.SystemAdminPage })));

export default function App() {
  return <Routes><Route element={<AppShell />}><Route index element={<Navigate to="/projects" replace />} /><Route path="projects" element={<ProjectsPage />} /><Route path="projects/:projectId/admin" element={<ProjectAdminPage />} /><Route path="projects/:projectId/workflows" element={<WorkflowListPage />} /><Route path="projects/:projectId/workflows/new" element={<WorkflowBuilderPage />} /><Route path="projects/:projectId/workflows/:workflowId/edit" element={<WorkflowBuilderPage />} /><Route path="credentials" element={<CredentialsPage />} /><Route path="runs" element={<RunsPage />} /><Route path="runs/:runId" element={<RunDetailPage />} /><Route path="admin" element={<SystemAdminPage />} /></Route></Routes>;
}
