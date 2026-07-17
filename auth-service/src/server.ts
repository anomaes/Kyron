import crypto from "node:crypto";
import express, { type Request, type Response } from "express";
import { parse, serialize } from "cookie";

type Identity = {
  email: string;
  name: string;
  avatar: string | null;
  gitlabUserId: number;
  gitlabUsername: string;
  expiresAt: number;
};

type State = { nonce: string; returnTo: string; expiresAt: number };

const required = (name: string): string => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
};

const config = {
  gitlabUrl: (process.env.GITLAB_URL ?? "https://gitlab.com").replace(/\/$/, ""),
  clientId: required("OAUTH_CLIENT_ID"),
  clientSecret: required("OAUTH_CLIENT_SECRET"),
  redirectUri: required("OAUTH_REDIRECT_URI"),
  signingKey: required("SESSION_SIGNING_KEY"),
  previousSigningKey: process.env.SESSION_PREVIOUS_SIGNING_KEY ?? "",
  maximumAge: Number(process.env.SESSION_MAX_AGE_SECONDS ?? 28_800),
  secure: (process.env.APP_ENV ?? "production") !== "development",
};

if (config.signingKey.length < 32) throw new Error("SESSION_SIGNING_KEY must have at least 32 characters");

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

const app = express();
app.disable("x-powered-by");

app.get("/auth/login", (request: Request, response: Response) => {
  const nonce = crypto.randomBytes(24).toString("base64url");
  const state: State = { nonce, returnTo: safeReturnTo(request.query.return_to), expiresAt: Date.now() + 10 * 60_000 };
  response.setHeader("Set-Cookie", serialize("kyron_oauth_state", sign(state), cookieOptions(600)));
  const authorize = new URL(`${config.gitlabUrl}/oauth/authorize`);
  authorize.searchParams.set("client_id", config.clientId);
  authorize.searchParams.set("redirect_uri", config.redirectUri);
  authorize.searchParams.set("response_type", "code");
  authorize.searchParams.set("scope", "read_user");
  authorize.searchParams.set("state", nonce);
  response.redirect(authorize.toString());
});

app.get("/auth/callback", async (request: Request, response: Response) => {
  const cookies = parse(request.headers.cookie ?? "");
  const state = verify<State>(cookies.kyron_oauth_state);
  if (!state || state.expiresAt < Date.now() || request.query.state !== state.nonce || typeof request.query.code !== "string") {
    response.status(401).send("OAuth state is invalid or expired"); return;
  }
  const tokenResponse = await fetch(`${config.gitlabUrl}/oauth/token`, {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: config.clientId, client_secret: config.clientSecret, code: request.query.code, grant_type: "authorization_code", redirect_uri: config.redirectUri }),
  });
  if (!tokenResponse.ok) { response.status(502).send("GitLab token exchange failed"); return; }
  const token = await tokenResponse.json() as { access_token?: string };
  if (!token.access_token) { response.status(502).send("GitLab returned no access token"); return; }
  const userResponse = await fetch(`${config.gitlabUrl}/api/v4/user`, { headers: { Authorization: `Bearer ${token.access_token}` } });
  if (!userResponse.ok) { response.status(502).send("GitLab user lookup failed"); return; }
  const user = await userResponse.json() as { id: number; username: string; name?: string; email?: string; public_email?: string; avatar_url?: string };
  const email = user.email || user.public_email;
  if (!email || !user.id || !user.username) { response.status(403).send("GitLab identity is incomplete"); return; }
  const identity: Identity = { email, name: user.name || user.username, avatar: user.avatar_url ?? null, gitlabUserId: user.id, gitlabUsername: user.username, expiresAt: Date.now() + config.maximumAge * 1000 };
  response.setHeader("Set-Cookie", [serialize("kyron_session", sign(identity), cookieOptions(config.maximumAge)), serialize("kyron_oauth_state", "", { ...cookieOptions(0), expires: new Date(0) })]);
  response.redirect(state.returnTo);
});

app.get("/auth/verify", (request: Request, response: Response) => {
  const identity = verify<Identity>(parse(request.headers.cookie ?? "").kyron_session);
  if (!identity || identity.expiresAt < Date.now()) {
    const returnTo = safeReturnTo(request.header("X-Forwarded-Uri"));
    response.redirect(302, `/auth/login?return_to=${encodeURIComponent(returnTo)}`); return;
  }
  response.setHeader("X-Token-User-Email", identity.email);
  response.setHeader("X-Token-User-Name", identity.name);
  if (identity.avatar) response.setHeader("X-Token-User-Avatar", identity.avatar);
  response.setHeader("X-Token-GitLab-User-Id", String(identity.gitlabUserId));
  response.setHeader("X-Token-GitLab-Username", identity.gitlabUsername);
  response.status(200).end();
});

app.get("/auth/logout", (_request: Request, response: Response) => {
  response.setHeader("Set-Cookie", serialize("kyron_session", "", { ...cookieOptions(0), expires: new Date(0) }));
  response.redirect("/");
});

app.get("/health", (_request, response) => response.json({ status: "ok" }));
app.listen(3001, "0.0.0.0", () => console.log("Kyron auth service listening on :3001"));
