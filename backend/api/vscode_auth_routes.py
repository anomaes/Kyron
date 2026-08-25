from __future__ import annotations

import html
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse

from backend.auth.dependencies import CurrentUser, DbSession
from backend.config import Settings, get_settings
from backend.schemas.vscode_auth import (
    VsCodeDeviceResponse,
    VsCodeRevokeRequest,
    VsCodeTokenIdentity,
    VsCodeTokenRequest,
    VsCodeTokenResponse,
)
from backend.services.vscode_auth_service import VsCodeAuthorizationError, VsCodeAuthService

router = APIRouter(prefix="/auth/vscode", tags=["VS Code authentication"])
internal_router = APIRouter(prefix="/internal/auth", tags=["internal authentication"])
PAGE_STYLE = """
body {
  margin: 0; min-height: 100vh; display: grid; place-items: center;
  background: #f3f2ed; color: #171914; font: 16px system-ui;
}
main {
  width: min(440px, calc(100% - 48px)); padding: 32px;
  border: 1px solid #ccc; background: white; box-shadow: 0 18px 50px #0001;
}
code {
  display: block; margin: 20px 0; padding: 16px; background: #f3f2ed;
  font-size: 24px; text-align: center; letter-spacing: .12em;
}
button {
  width: 100%; padding: 13px 16px; border: 0; border-radius: 5px;
  background: #171914; color: white; font: inherit; cursor: pointer;
}
small { display: block; margin-top: 16px; color: #60645d; }
"""


def _service(
    db: DbSession, settings: Annotated[Settings, Depends(get_settings)]
) -> VsCodeAuthService:
    return VsCodeAuthService(db, settings)


Service = Annotated[VsCodeAuthService, Depends(_service)]


@router.post("/device", response_model=VsCodeDeviceResponse)
async def create_device_authorization(
    request: Request, response: Response, service: Service
) -> VsCodeDeviceResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    issued = await service.issue_device_code()
    base_url = str(request.base_url).rstrip("/")
    verification_uri = f"{base_url}/api/auth/vscode/authorize"
    return VsCodeDeviceResponse(
        device_code=issued.device_code,
        user_code=issued.user_code,
        verification_uri=verification_uri,
        verification_uri_complete=f"{verification_uri}?user_code={quote(issued.user_code)}",
        expires_in=issued.expires_in,
        interval=issued.interval,
    )


@router.get("/authorize", response_class=HTMLResponse)
async def show_device_authorization(
    user: CurrentUser,
    service: Service,
    user_code: Annotated[str, Query(min_length=8, max_length=9)],
) -> HTMLResponse:
    try:
        pending = await service.get_pending_device(user_code)
    except VsCodeAuthorizationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    safe_code = html.escape(pending.user_code)
    safe_user = html.escape(user.display_name)
    # Keep the action relative so deployments mounted below a URL prefix (for
    # example, /kyron) submit back through the same public ingress path.
    form_action = f"?user_code={quote(pending.user_code)}"
    content = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Connect VS Code to Kyron</title>
<style>{PAGE_STYLE}</style></head>
<body><main><h1>Connect VS Code</h1>
<p>Signed in as <strong>{safe_user}</strong>. Confirm that VS Code displays this code:</p>
<code>{safe_code}</code><form method="post" action="{form_action}">
<button type="submit">Connect VS Code</button></form>
<small>Only approve a code you initiated from the Kyron extension.</small>
</main></body></html>"""
    return HTMLResponse(content, headers={"Cache-Control": "no-store"})


@router.post("/authorize", response_class=HTMLResponse)
async def approve_device_authorization(
    user: CurrentUser,
    service: Service,
    user_code: Annotated[str, Query(min_length=8, max_length=9)],
) -> HTMLResponse:
    try:
        await service.approve_device(user_code, user)
    except VsCodeAuthorizationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>VS Code connected</title>
<style>{PAGE_STYLE}</style></head><body><main><h1>VS Code connected</h1>
<p>You can close this page and return to VS Code.</p></main></body></html>""",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/token", response_model=VsCodeTokenResponse)
async def exchange_token(
    request: VsCodeTokenRequest, response: Response, service: Service
) -> VsCodeTokenResponse | JSONResponse:
    try:
        if request.grant_type == "device_code":
            assert request.device_code is not None
            issued = await service.exchange_device_code(request.device_code)
        else:
            assert request.refresh_token is not None
            issued = await service.refresh(request.refresh_token)
    except VsCodeAuthorizationError as exc:
        return JSONResponse(
            {"error": exc.code, "error_description": str(exc)},
            status_code=status.HTTP_400_BAD_REQUEST,
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return VsCodeTokenResponse(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in=issued.expires_in,
    )


@router.post("/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(request: VsCodeRevokeRequest, service: Service) -> Response:
    await service.revoke(request.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@internal_router.post(
    "/vscode-token", response_model=VsCodeTokenIdentity, include_in_schema=False
)
async def verify_vscode_token(
    service: Service,
    authorization: Annotated[str | None, Header()] = None,
) -> VsCodeTokenIdentity:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        user = await service.identity_for_access_token(authorization.removeprefix("Bearer "))
    except VsCodeAuthorizationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    return VsCodeTokenIdentity(
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        provider=user.provider,
        provider_user_id=user.provider_user_id,
        provider_username=user.provider_username,
    )
