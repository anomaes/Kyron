import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { CredentialsPage } from "./pages/CredentialsPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { RunsPage } from "./pages/RunsPage";
import { WorkflowBuilderPage } from "./pages/WorkflowBuilderPage";
import { WorkflowListPage } from "./pages/WorkflowListPage";

export default function App() {
  return <Routes><Route element={<AppShell />}><Route index element={<Navigate to="/projects" replace />} /><Route path="projects" element={<ProjectsPage />} /><Route path="projects/:projectId/workflows" element={<WorkflowListPage />} /><Route path="projects/:projectId/workflows/new" element={<WorkflowBuilderPage />} /><Route path="projects/:projectId/workflows/:workflowId/edit" element={<WorkflowBuilderPage />} /><Route path="credentials" element={<CredentialsPage />} /><Route path="runs" element={<RunsPage />} /><Route path="runs/:runId" element={<RunDetailPage />} /></Route></Routes>;
}
