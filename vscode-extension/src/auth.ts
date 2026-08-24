import * as vscode from "vscode";

const ACCESS_TOKEN_KEY = "kyron.vscode.accessToken";
const REFRESH_TOKEN_KEY = "kyron.vscode.refreshToken";
const ACCESS_EXPIRY_KEY = "kyron.vscode.accessExpiry";
const SERVER_KEY = "kyron.vscode.serverUrl";

type DeviceAuthorization = {
  device_code: string;
  user_code: string;
  verification_uri_complete: string;
  expires_in: number;
  interval: number;
};

type TokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: "Bearer";
  expires_in: number;
};

type ErrorResponse = {
  error?: string;
  error_description?: string;
  detail?: string;
};

export class AuthenticationError extends Error {
  constructor(
    message: string,
    readonly code?: string,
  ) {
    super(message);
  }
}

export class DeviceAuthentication {
  private refreshPromise?: Promise<string>;

  constructor(private readonly context: vscode.ExtensionContext) {}

  async hasSession(serverUrl: string): Promise<boolean> {
    const storedServer = this.context.globalState.get<string>(SERVER_KEY);
    return storedServer === serverUrl && Boolean(await this.context.secrets.get(REFRESH_TOKEN_KEY));
  }

  async signIn(serverUrl: string): Promise<void> {
    const device = await this.post<DeviceAuthorization>(serverUrl, "/api/auth/vscode/device", {});
    const choice = await vscode.window.showInformationMessage(
      `Confirm code ${device.user_code} in Kyron to connect VS Code.`,
      { modal: true, detail: "Only approve this code if it matches the code shown in your browser." },
      "Open Kyron",
    );
    if (choice !== "Open Kyron") {
      throw new AuthenticationError("Kyron connection was cancelled");
    }

    const verificationUrl = new URL(`${serverUrl}/api/auth/vscode/authorize`);
    verificationUrl.searchParams.set("user_code", device.user_code);
    const opened = await vscode.env.openExternal(vscode.Uri.parse(verificationUrl.toString()));
    if (!opened) {
      throw new AuthenticationError("Could not open the Kyron authorization page");
    }

    const tokens = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: `Waiting for Kyron approval (${device.user_code})`,
        cancellable: true,
      },
      async (_progress, cancellation) => {
        const deadline = Date.now() + device.expires_in * 1_000;
        while (Date.now() < deadline) {
          if (cancellation.isCancellationRequested) {
            throw new AuthenticationError("Kyron connection was cancelled");
          }
          try {
            return await this.post<TokenResponse>(serverUrl, "/api/auth/vscode/token", {
              grant_type: "device_code",
              device_code: device.device_code,
            });
          } catch (error) {
            if (!(error instanceof AuthenticationError) || error.code !== "authorization_pending") {
              throw error;
            }
          }
          await delay(Math.max(device.interval, 1) * 1_000, cancellation);
        }
        throw new AuthenticationError("The Kyron connection code expired", "expired_token");
      },
    );
    await this.store(serverUrl, tokens);
  }

  async accessToken(serverUrl: string): Promise<string | undefined> {
    if (!(await this.hasSession(serverUrl))) {
      return undefined;
    }
    const expiry = this.context.globalState.get<number>(ACCESS_EXPIRY_KEY, 0);
    const accessToken = await this.context.secrets.get(ACCESS_TOKEN_KEY);
    if (accessToken && expiry > Date.now() + 30_000) {
      return accessToken;
    }
    return this.refresh(serverUrl);
  }

  async refresh(serverUrl: string): Promise<string> {
    if (this.refreshPromise) return this.refreshPromise;
    const operation = this.refreshOnce(serverUrl);
    this.refreshPromise = operation;
    try {
      return await operation;
    } finally {
      if (this.refreshPromise === operation) this.refreshPromise = undefined;
    }
  }

  private async refreshOnce(serverUrl: string): Promise<string> {
    const refreshToken = await this.context.secrets.get(REFRESH_TOKEN_KEY);
    if (!refreshToken || this.context.globalState.get<string>(SERVER_KEY) !== serverUrl) {
      throw new AuthenticationError("Connect VS Code to Kyron first");
    }
    try {
      const tokens = await this.post<TokenResponse>(serverUrl, "/api/auth/vscode/token", {
        grant_type: "refresh_token",
        refresh_token: refreshToken,
      });
      await this.store(serverUrl, tokens);
      return tokens.access_token;
    } catch (error) {
      if (error instanceof AuthenticationError && error.code === "invalid_grant") {
        await this.clear();
      }
      throw error;
    }
  }

  async signOut(): Promise<void> {
    if (this.refreshPromise) {
      try {
        await this.refreshPromise;
      } catch {
        // Continue clearing credentials after a failed in-flight refresh.
      }
    }
    const serverUrl = this.context.globalState.get<string>(SERVER_KEY);
    const refreshToken = await this.context.secrets.get(REFRESH_TOKEN_KEY);
    if (serverUrl && refreshToken) {
      try {
        await this.post<undefined>(serverUrl, "/api/auth/vscode/revoke", {
          refresh_token: refreshToken,
        });
      } catch {
        // Local removal still disconnects this client if the deployment is unavailable.
      }
    }
    await this.clear();
  }

  private async store(serverUrl: string, tokens: TokenResponse): Promise<void> {
    await Promise.all([
      this.context.secrets.store(ACCESS_TOKEN_KEY, tokens.access_token),
      this.context.secrets.store(REFRESH_TOKEN_KEY, tokens.refresh_token),
      this.context.globalState.update(ACCESS_EXPIRY_KEY, Date.now() + tokens.expires_in * 1_000),
      this.context.globalState.update(SERVER_KEY, serverUrl),
    ]);
  }

  private async clear(): Promise<void> {
    await Promise.all([
      this.context.secrets.delete(ACCESS_TOKEN_KEY),
      this.context.secrets.delete(REFRESH_TOKEN_KEY),
      this.context.globalState.update(ACCESS_EXPIRY_KEY, undefined),
      this.context.globalState.update(SERVER_KEY, undefined),
    ]);
  }

  private async post<T>(serverUrl: string, path: string, body: object): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${serverUrl}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch {
      throw new AuthenticationError("Could not reach the Kyron deployment");
    }
    if (!response.ok) {
      const payload = await parseJson<ErrorResponse>(response);
      throw new AuthenticationError(
        payload?.error_description ?? payload?.detail ?? `Kyron returned HTTP ${response.status}`,
        payload?.error,
      );
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }
}

async function parseJson<T>(response: Response): Promise<T | undefined> {
  try {
    return (await response.json()) as T;
  } catch {
    return undefined;
  }
}

async function delay(milliseconds: number, cancellation: vscode.CancellationToken): Promise<void> {
  await new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, milliseconds);
    cancellation.onCancellationRequested(() => {
      clearTimeout(timer);
      resolve();
    });
  });
}
