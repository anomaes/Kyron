import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Workflow } from "../types";
import type { CatalogStatus, ExpansionSnapshot, ReviewBranch } from "./projection";

type ExpansionContextValue = {
  projectId: string;
  catalogById: ReadonlyMap<string, Workflow>;
  catalogStatus: CatalogStatus;
  snapshot: ExpansionSnapshot;
  liveMessage: string;
  expand: (
    instanceKey: string,
    topLevelKey: string,
    workflowId: string,
    workflowName: string,
    nodeCount: number,
  ) => void;
  collapse: (instanceKey: string, workflowName: string) => void;
  selectReviewTab: (
    instanceKey: string,
    branch: ReviewBranch,
    workflowId: string,
    workflowName: string,
  ) => void;
  reset: (message?: string) => void;
};

const ExpansionContext = createContext<ExpansionContextValue | null>(null);

type Props = {
  projectId: string;
  catalogById: ReadonlyMap<string, Workflow>;
  catalogStatus: CatalogStatus;
  resetKey: string;
  children: ReactNode;
};

function withoutBranch(keys: ReadonlySet<string>, instanceKey: string): Set<string> {
  return new Set([...keys].filter((key) => key !== instanceKey && !key.startsWith(`${instanceKey}::`)));
}

export function WorkflowExpansionProvider({
  projectId,
  catalogById,
  catalogStatus,
  resetKey,
  children,
}: Props) {
  const [activeTopLevelKey, setActiveTopLevelKey] = useState<string | null>(null);
  const [expandedKeys, setExpandedKeys] = useState<ReadonlySet<string>>(() => new Set());
  const [reviewTabs, setReviewTabs] = useState<ReadonlyMap<string, ReviewBranch>>(() => new Map());
  const [referenceByKey, setReferenceByKey] = useState<ReadonlyMap<string, string>>(() => new Map());
  const [liveMessage, setLiveMessage] = useState("");

  const reset = useCallback((message = "") => {
    setActiveTopLevelKey(null);
    setExpandedKeys(new Set());
    setReviewTabs(new Map());
    setReferenceByKey(new Map());
    setLiveMessage(message);
  }, []);

  useEffect(() => {
    reset();
  }, [reset, resetKey]);

  const expand = useCallback((
    instanceKey: string,
    topLevelKey: string,
    workflowId: string,
    workflowName: string,
    nodeCount: number,
  ) => {
    setExpandedKeys((keys) => activeTopLevelKey === topLevelKey
      ? new Set(keys).add(instanceKey)
      : new Set([topLevelKey]));
    setActiveTopLevelKey(topLevelKey);
    setReferenceByKey((references) => new Map(references).set(instanceKey, workflowId));
    setLiveMessage(`${workflowName} expanded, ${nodeCount} node${nodeCount === 1 ? "" : "s"}`);
  }, [activeTopLevelKey]);

  const collapse = useCallback((instanceKey: string, workflowName: string) => {
    setExpandedKeys((keys) => withoutBranch(keys, instanceKey));
    setReviewTabs((tabs) => new Map([...tabs].filter(([key]) => key !== instanceKey && !key.startsWith(`${instanceKey}::`))));
    setReferenceByKey((references) => new Map([...references].filter(([key]) => key !== instanceKey && !key.startsWith(`${instanceKey}::`))));
    setActiveTopLevelKey((current) => current === instanceKey ? null : current);
    setLiveMessage(`${workflowName} collapsed`);
  }, []);

  const selectReviewTab = useCallback((
    instanceKey: string,
    branch: ReviewBranch,
    workflowId: string,
    workflowName: string,
  ) => {
    setReviewTabs((tabs) => new Map(tabs).set(instanceKey, branch));
    setExpandedKeys((keys) => {
      const next = withoutBranch(keys, instanceKey);
      next.add(instanceKey);
      return next;
    });
    setReferenceByKey((references) => new Map(references).set(instanceKey, workflowId));
    setLiveMessage(`Showing ${branch} workflow ${workflowName}`);
  }, []);

  const snapshot = useMemo<ExpansionSnapshot>(() => ({
    activeTopLevelKey,
    expandedKeys,
    reviewTabs,
    referenceByKey,
  }), [activeTopLevelKey, expandedKeys, reviewTabs, referenceByKey]);

  const value = useMemo<ExpansionContextValue>(() => ({
    projectId,
    catalogById,
    catalogStatus,
    snapshot,
    liveMessage,
    expand,
    collapse,
    selectReviewTab,
    reset,
  }), [
    projectId,
    catalogById,
    catalogStatus,
    snapshot,
    liveMessage,
    expand,
    collapse,
    selectReviewTab,
    reset,
  ]);

  return <ExpansionContext.Provider value={value}>{children}</ExpansionContext.Provider>;
}

export function useWorkflowExpansion(): ExpansionContextValue {
  const value = useContext(ExpansionContext);
  if (!value) throw new Error("Workflow preview controls require WorkflowExpansionProvider");
  return value;
}

export function workflowReferenceSignature(workflows: readonly Workflow[]): string {
  return workflows
    .map((workflow) => {
      const references = workflow.nodes
        .filter((node) => node.type === "subworkflow" || node.type === "review_loop")
        .map((node) => [
          node.id,
          String(node.config.workflow_id ?? ""),
          String(node.config.initial_workflow_id ?? ""),
          String(node.config.revision_workflow_id ?? ""),
        ].join(":"))
        .sort()
        .join(",");
      return `${workflow.id}[${references}]`;
    })
    .sort()
    .join("|");
}
