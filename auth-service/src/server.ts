import crypto from "node:crypto";
import express, { type Request, type Response } from "express";
import { parse, serialize } from "cookie";

type Provider = "gitlab" | "github";
type Identity = {
  email: string;
  name: string;
  avatar: string | null;
  provider: Provider;
  providerUserId: string;
  providerUsername: string;
  expiresAt: number;
};
type State = { nonce: string; provider: Provider; returnTo: string; expiresAt: number };
type OAuthConfig = { clientId: string; clientSecret: string };

const required = (name: string): string => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
};
const optionalOAuth = (provider: Provider): OAuthConfig | null => {
  const prefix = provider.toUpperCase();
  const legacyId = provider === "gitlab" ? process.env.OAUTH_CLIENT_ID : undefined;
  const legacySecret = provider === "gitlab" ? process.env.OAUTH_CLIENT_SECRET : undefined;
  const clientId = process.env[`${prefix}_OAUTH_CLIENT_ID`] ?? legacyId ?? "";
  const clientSecret = process.env[`${prefix}_OAUTH_CLIENT_SECRET`] ?? legacySecret ?? "";
  if (!clientId && !clientSecret) return null;
  if (!clientId || !clientSecret) throw new Error(`${prefix}_OAUTH_CLIENT_ID and ${prefix}_OAUTH_CLIENT_SECRET must be configured together`);
  return { clientId, clientSecret };
};

const config = {
  gitlabUrl: (process.env.GITLAB_URL ?? "https://gitlab.com").replace(/\/$/, ""),
  githubWebUrl: (process.env.GITHUB_WEB_URL ?? "https://github.com").replace(/\/$/, ""),
  githubApiUrl: (process.env.GITHUB_API_URL ?? "https://api.github.com").replace(/\/$/, ""),
  oauth: { gitlab: optionalOAuth("gitlab"), github: optionalOAuth("github") },
  redirectUri: required("OAUTH_REDIRECT_URI"),
  signingKey: required("SESSION_SIGNING_KEY"),
  previousSigningKey: process.env.SESSION_PREVIOUS_SIGNING_KEY ?? "",
  maximumAge: Number(process.env.SESSION_MAX_AGE_SECONDS ?? 28_800),
  secure: (process.env.APP_ENV ?? "production") !== "development",
};

if (config.signingKey.length < 32) throw new Error("SESSION_SIGNING_KEY must have at least 32 characters");
if (!config.oauth.gitlab && !config.oauth.github) throw new Error("At least one OAuth provider must be configured");

function sign<T extends object>(payload: T, key = config.signingKey): string {
  const encoded = Buffer.from(JSON.stringify(payload)).toString("base64url");
  const signature = crypto.createHmac("sha256", key).update(encoded).digest("base64url");
  return `${encoded}.${signature}`;
}

function verify<T>(token: string | undefined): T | null {
  if (!token) return null;
  const [encoded, provided] = token.split(".");
  if (!encoded || !provided) return null;
  for (const key of [config.signingKey, config.previousSigningKey].filter(Boolean)) {
    const expected = crypto.createHmac("sha256", key).update(encoded).digest("base64url");
    const left = Buffer.from(provided); const right = Buffer.from(expected);
    if (left.length !== right.length || !crypto.timingSafeEqual(left, right)) continue;
    try { return JSON.parse(Buffer.from(encoded, "base64url").toString("utf8")) as T; } catch { return null; }
  }
  return null;
}

function cookieOptions(maxAge: number) {
  return { httpOnly: true, secure: config.secure, sameSite: "lax" as const, path: "/", maxAge };
}
function safeReturnTo(value: unknown): string {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) return "/";
  return value;
}
function requestedProvider(value: unknown): Provider | null {
  return value === "gitlab" || value === "github" ? value : null;
}
function providerConfig(provider: Provider): OAuthConfig {
  const value = config.oauth[provider];
  if (!value) throw new Error(`${provider} OAuth is not configured`);
  return value;
}

const app = express();
app.disable("x-powered-by");

app.get("/auth/login", (request: Request, response: Response) => {
  const provider = requestedProvider(request.query.provider);
  const returnTo = safeReturnTo(request.query.return_to);
  if (!provider) {
    const links = (["gitlab", "github"] as Provider[])
      .filter((item) => config.oauth[item])
      .map((item) => `<a href="/auth/login?provider=${item}&amp;return_to=${encodeURIComponent(returnTo)}">Continue with ${item === "gitlab" ? "GitLab" : "GitHub"}</a>`)
      .join("");
    response.type("html").send(`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Sign in to Kyron</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f3f2ed;color:#171914;font:16px system-ui}.card{width:min(360px,calc(100% - 48px));padding:32px;border:1px solid #ccc;background:white;box-shadow:0 18px 50px #0001}h1{margin-top:0}.links{display:grid;gap:12px}a{padding:13px 16px;background:#171914;color:white;text-decoration:none;text-align:center;border-radius:5px}</style></head><body><main class="card"><h1>Sign in to Kyron</h1><p>Choose the code host you want to use for this session.</p><div class="links">${links}</div></main></body></html>`);
    return;
  }
  if (!config.oauth[provider]) { response.status(404).send(`${provider} OAuth is not configured`); return; }
  const nonce = crypto.randomBytes(24).toString("base64url");
  const state: State = { nonce, provider, returnTo, expiresAt: Date.now() + 10 * 60_000 };
  response.setHeader("Set-Cookie", serialize("kyron_oauth_state", sign(state), cookieOptions(600)));
  const oauth = providerConfig(provider);
  const authorize = new URL(provider === "gitlab" ? `${config.gitlabUrl}/oauth/authorize` : `${config.githubWebUrl}/login/oauth/authorize`);
  authorize.searchParams.set("client_id", oauth.clientId);
  authorize.searchParams.set("redirect_uri", config.redirectUri);
  authorize.searchParams.set("scope", provider === "gitlab" ? "read_user" : "read:user user:email");
  authorize.searchParams.set("state", nonce);
  if (provider === "gitlab") authorize.searchParams.set("response_type", "code");
  response.redirect(authorize.toString());
});

app.get("/auth/callback", async (request: Request, response: Response) => {
  const state = verify<State>(parse(request.headers.cookie ?? "").kyron_oauth_state);
  if (!state || !requestedProvider(state.provider) || state.expiresAt < Date.now() || request.query.state !== state.nonce || typeof request.query.code !== "string") {
    response.status(401).send("OAuth state is invalid or expired"); return;
  }
  try {
    const identity = state.provider === "gitlab"
      ? await gitlabIdentity(request.query.code)
      : await githubIdentity(request.query.code);
    identity.expiresAt = Date.now() + config.maximumAge * 1000;
    response.setHeader("Set-Cookie", [
      serialize("kyron_session", sign(identity), cookieOptions(config.maximumAge)),
      serialize("kyron_oauth_state", "", { ...cookieOptions(0), expires: new Date(0) }),
    ]);
    response.redirect(state.returnTo);
  } catch (error) {
    response.status(502).send(error instanceof Error ? error.message : "OAuth login failed");
  }
});

async function gitlabIdentity(code: string): Promise<Identity> {
  const oauth = providerConfig("gitlab");
  const tokenResponse = await fetch(`${config.gitlabUrl}/oauth/token`, {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: oauth.clientId, client_secret: oauth.clientSecret, code, grant_type: "authorization_code", redirect_uri: config.redirectUri }),
  });
  if (!tokenResponse.ok) throw new Error("GitLab token exchange failed");
  const token = await tokenResponse.json() as { access_token?: string };
  if (!token.access_token) throw new Error("GitLab returned no access token");
  const userResponse = await fetch(`${config.gitlabUrl}/api/v4/user`, { headers: { Authorization: `Bearer ${token.access_token}` } });
  if (!userResponse.ok) throw new Error("GitLab user lookup failed");
  const user = await userResponse.json() as { id?: number; username?: string; name?: string; email?: string; public_email?: string; avatar_url?: string };
  const email = user.email || user.public_email;
  if (!email || !user.id || !user.username) throw new Error("GitLab identity is incomplete");
  return { email, name: user.name || user.username, avatar: user.avatar_url ?? null, provider: "gitlab", providerUserId: String(user.id), providerUsername: user.username, expiresAt: 0 };
}

async function githubIdentity(code: string): Promise<Identity> {
  const oauth = providerConfig("github");
  const tokenResponse = await fetch(`${config.githubWebUrl}/login/oauth/access_token`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: oauth.clientId, client_secret: oauth.clientSecret, code, redirect_uri: config.redirectUri }),
  });
  if (!tokenResponse.ok) throw new Error("GitHub token exchange failed");
  const token = await tokenResponse.json() as { access_token?: string };
  if (!token.access_token) throw new Error("GitHub returned no access token");
  const headers = { Authorization: `Bearer ${token.access_token}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" };
  const userResponse = await fetch(`${config.githubApiUrl}/user`, { headers });
  if (!userResponse.ok) throw new Error("GitHub user lookup failed");
  const user = await userResponse.json() as { id?: number; login?: string; name?: string; email?: string; avatar_url?: string };
  let email = user.email;
  if (!email) {
    const emailsResponse = await fetch(`${config.githubApiUrl}/user/emails`, { headers });
    if (!emailsResponse.ok) throw new Error("GitHub email lookup failed");
    const emails = await emailsResponse.json() as Array<{ email: string; primary: boolean; verified: boolean }>;
    email = emails.find((item) => item.primary && item.verified)?.email;
  }
  if (!email || !user.id || !user.login) throw new Error("GitHub identity is incomplete");
  return { email, name: user.name || user.login, avatar: user.avatar_url ?? null, provider: "github", providerUserId: String(user.id), providerUsername: user.login, expiresAt: 0 };
}

app.get("/auth/verify", (request: Request, response: Response) => {
  const identity = verify<Identity>(parse(request.headers.cookie ?? "").kyron_session);
  if (!identity || !requestedProvider(identity.provider) || !identity.providerUserId || !identity.providerUsername || identity.expiresAt < Date.now()) {
    const returnTo = safeReturnTo(request.header("X-Forwarded-Uri"));
    response.redirect(302, `/auth/login?return_to=${encodeURIComponent(returnTo)}`); return;
  }
  response.setHeader("X-Token-User-Email", identity.email);
  response.setHeader("X-Token-User-Name", identity.name);
  if (identity.avatar) response.setHeader("X-Token-User-Avatar", identity.avatar);
  response.setHeader("X-Token-Provider", identity.provider);
  response.setHeader("X-Token-Provider-User-Id", identity.providerUserId);
  response.setHeader("X-Token-Provider-Username", identity.providerUsername);
  response.status(200).end();
});

app.get("/auth/logout", (_request: Request, response: Response) => {
  response.setHeader("Set-Cookie", serialize("kyron_session", "", { ...cookieOptions(0), expires: new Date(0) }));
  response.redirect("/");
});
app.get("/health", (_request, response) => response.json({ status: "ok" }));
app.listen(3001, "0.0.0.0", () => console.log("Kyron auth service listening on :3001"));
