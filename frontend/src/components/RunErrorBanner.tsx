export function RunErrorBanner({
  errorType,
  errorMessage,
}: {
  errorType: string | null;
  errorMessage: string | null;
}) {
  if (!errorMessage) return null;

  return <div className="run-error-banner" role="alert">
    <span>Execution error</span>
    <strong>{(errorType ?? "RUN_ERROR").replaceAll("_", " ")}</strong>
    <p>{errorMessage}</p>
  </div>;
}
