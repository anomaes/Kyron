import { useId } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PiModelsCatalog } from "../types";

type Props = {
  provider: string;
  model: string;
  onProviderChange: (value: string) => void;
  onModelChange: (value: string) => void;
  providerPlaceholder?: string;
  modelPlaceholder?: string;
};

export function PiProviderFields({
  provider,
  model,
  onProviderChange,
  onModelChange,
  providerPlaceholder = "Inherit project default",
  modelPlaceholder = "Inherit project default",
}: Props) {
  const id = useId().replaceAll(":", "");
  const catalog = useQuery({
    queryKey: ["pi-models-catalog"],
    queryFn: () => api<PiModelsCatalog>("/pi/models/catalog"),
    staleTime: 30_000,
  });
  const selected = catalog.data?.providers.find((item) => item.id === provider);
  const modelOptions = selected?.models ?? catalog.data?.providers.flatMap((item) => item.models) ?? [];
  return <div className="pi-provider-fields">
    <label>Pi provider
      <input
        list={`${id}-providers`}
        value={provider}
        placeholder={providerPlaceholder}
        onChange={(event) => onProviderChange(event.target.value)}
      />
      <datalist id={`${id}-providers`}>{catalog.data?.providers.map((item) => <option key={item.id} value={item.id} />)}</datalist>
    </label>
    <label>Pi model
      <input
        list={`${id}-models`}
        value={model}
        placeholder={modelPlaceholder}
        onChange={(event) => onModelChange(event.target.value)}
      />
      <datalist id={`${id}-models`}>{modelOptions.map((item) => <option key={item} value={item} />)}</datalist>
    </label>
    {selected && <div className="pi-selection-help">
      <span>Configured provider</span>
      <strong>{selected.models.length ? `${selected.models.length} model${selected.models.length === 1 ? "" : "s"} available` : "Uses Pi's built-in models"}</strong>
      {selected.required_credentials.length > 0 && <small>Requires Kyron credential{selected.required_credentials.length === 1 ? "" : "s"}: {selected.required_credentials.join(", ")}</small>}
    </div>}
  </div>;
}
