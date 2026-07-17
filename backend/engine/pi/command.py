def build_pi_command(
    prompt: str, provider: str | None = None, model: str | None = None
) -> list[str]:
    command = ["pi", "--mode", "json", "--no-session", "--no-approve"]
    if provider:
        command.extend(["--provider", provider])
    if model:
        command.extend(["--model", model])
    command.append(prompt)
    return command
