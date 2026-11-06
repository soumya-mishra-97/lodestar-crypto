from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status

from lodestar.application.auth import TokenPair
from lodestar.domain.errors import AuthenticationError
from lodestar.interfaces.http.deps import ContainerDep, PrincipalDep, rate_limit
from lodestar.interfaces.http.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE = "ls_refresh"


def _set_refresh_cookie(response: Response, pair: TokenPair, *, secure: bool, max_age: int) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        pair.refresh_token,
        max_age=max_age,
        httponly=True,  # unreadable from JavaScript (XSS cannot steal it)
        secure=secure,
        samesite="strict",  # never sent cross-site (CSRF)
        path="/api/v1/auth",  # only sent to auth endpoints
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("login", per="ip"))],
)
async def register(body: RegisterRequest, c: ContainerDep) -> UserResponse:
    user = await c.auth.register(body.email, body.password)
    return UserResponse(id=str(user.id), email=user.email, role=user.role.value)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit("login", per="ip"))])
async def login(body: LoginRequest, response: Response, c: ContainerDep) -> TokenResponse:
    pair = await c.auth.login(body.email, body.password)
    _set_refresh_cookie(response, pair, secure=c.settings.is_production, max_age=c.settings.refresh_token_ttl_seconds)
    return TokenResponse(access_token=pair.access_token, expires_in=pair.expires_in)


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(rate_limit("login", per="ip"))])
async def refresh(
    response: Response, c: ContainerDep, ls_refresh: Annotated[str | None, Cookie()] = None
) -> TokenResponse:
    if not ls_refresh:
        raise AuthenticationError("No refresh token")
    pair = await c.auth.refresh(ls_refresh)
    _set_refresh_cookie(response, pair, secure=c.settings.is_production, max_age=c.settings.refresh_token_ttl_seconds)
    return TokenResponse(access_token=pair.access_token, expires_in=pair.expires_in)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, c: ContainerDep, ls_refresh: Annotated[str | None, Cookie()] = None) -> None:
    if ls_refresh:
        await c.auth.logout(ls_refresh)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")


@router.get("/me", response_model=UserResponse)
async def me(principal: PrincipalDep, c: ContainerDep) -> UserResponse:
    user = await c.auth.get_user(principal.user_id)
    return UserResponse(id=str(user.id), email=user.email, role=user.role.value)
