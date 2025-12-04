"""OIDC helper utilities for Single Sign-On integrations."""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException
from jose import JWTError, jwt


@dataclass
class OIDCProviderConfig:
    """Runtime configuration for a single OIDC identity provider."""

    name: str
    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: List[str] = field(default_factory=lambda: ["openid", "profile", "email"])
    tenant_claim: str = "tid"
    role_claim: str = "roles"
    default_role: str = "viewer"
    default_tenant: str = "default"


class OIDCProvider:
    """Wrapper that handles metadata, JWKS caching, and token verification."""

    def __init__(self, config: OIDCProviderConfig, cache_ttl: int = 3600):
        self.config = config
        self.cache_ttl = cache_ttl
        self._metadata: Optional[Dict[str, Any]] = None
        self._metadata_fetched_at: float = 0
        self._jwks: Optional[Dict[str, Any]] = None
        self._jwks_fetched_at: float = 0
        self._lock = asyncio.Lock()

    async def _fetch_metadata(self) -> Dict[str, Any]:
        async with self._lock:
            if self._metadata and (time.time() - self._metadata_fetched_at) < self.cache_ttl:
                return self._metadata

            discovery_url = f"{self.config.issuer.rstrip('/')}/.well-known/openid-configuration"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(discovery_url)
                response.raise_for_status()
                self._metadata = response.json()
                self._metadata_fetched_at = time.time()
                # Force JWKS reload on metadata refresh
                self._jwks = None
                self._jwks_fetched_at = 0
            return self._metadata

    async def _fetch_jwks(self) -> Dict[str, Any]:
        metadata = await self._fetch_metadata()
        jwks_uri = metadata.get("jwks_uri")
        if not jwks_uri:
            raise HTTPException(status_code=500, detail="OIDC provider missing jwks_uri")

        async with self._lock:
            if self._jwks and (time.time() - self._jwks_fetched_at) < self.cache_ttl:
                return self._jwks

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(jwks_uri)
                response.raise_for_status()
                self._jwks = response.json()
                self._jwks_fetched_at = time.time()
            return self._jwks

    async def get_metadata(self) -> Dict[str, Any]:
        return await self._fetch_metadata()

    async def exchange_code(
        self,
        code: str,
        code_verifier: str,
        redirect_uri: Optional[str] = None,
    ) -> Dict[str, Any]:
        metadata = await self._fetch_metadata()
        token_endpoint = metadata.get("token_endpoint")
        if not token_endpoint:
            raise HTTPException(status_code=500, detail="OIDC provider missing token_endpoint")

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri or self.config.redirect_uri,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(token_endpoint, data=data, headers={"Accept": "application/json"})
            if response.status_code >= 400:
                raise HTTPException(status_code=401, detail="OIDC token exchange failed")
            return response.json()

    async def verify_id_token(self, id_token: str) -> Dict[str, Any]:
        jwks = await self._fetch_jwks()
        headers = jwt.get_unverified_header(id_token)
        kid = headers.get("kid")
        key = None
        for jwk_key in jwks.get("keys", []):
            if jwk_key.get("kid") == kid:
                key = jwk_key
                break

        if not key:
            raise HTTPException(status_code=401, detail="OIDC signing key mismatch")

        try:
            algorithms = [headers.get("alg", "RS256")]
            claims = jwt.decode(
                id_token,
                key,
                algorithms=algorithms,
                audience=self.config.client_id,
                issuer=self.config.issuer,
            )
            return claims
        except JWTError as exc:
            raise HTTPException(status_code=401, detail=f"Invalid ID token: {exc}") from exc

    async def public_metadata(self) -> Dict[str, Any]:
        metadata = await self._fetch_metadata()
        return {
            "name": self.config.name,
            "issuer": self.config.issuer,
            "authorization_endpoint": metadata.get("authorization_endpoint"),
            "scopes": self.config.scopes,
            "redirect_uri": self.config.redirect_uri,
        }


def _load_provider_configs() -> Dict[str, OIDCProviderConfig]:
    raw_config = os.getenv("OIDC_PROVIDER_CONFIG")
    if not raw_config:
        config_path = os.getenv("OIDC_PROVIDER_CONFIG_FILE")
        if config_path and os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as fp:
                raw_config = fp.read()

    if not raw_config:
        return {}

    parsed = json.loads(raw_config)
    if isinstance(parsed, dict) and "providers" in parsed:
        parsed = parsed["providers"]

    providers: Dict[str, OIDCProviderConfig] = {}
    if isinstance(parsed, dict):
        items = parsed.items()
    elif isinstance(parsed, list):
        items = ((item.get("name"), item) for item in parsed)
    else:
        raise ValueError("OIDC provider config must be dict or list")

    for name, cfg in items:
        if not name or not isinstance(cfg, dict):
            continue
        providers[name] = OIDCProviderConfig(name=name, **cfg)
    return providers


class OIDCManager:
    """Factory/cache for configured OIDC providers."""

    def __init__(self):
        self.providers = {
            name: OIDCProvider(config)
            for name, config in _load_provider_configs().items()
        }

    def is_enabled(self) -> bool:
        return bool(self.providers)

    def get_provider(self, name: str) -> OIDCProvider:
        provider = self.providers.get(name)
        if not provider:
            raise HTTPException(status_code=404, detail=f"OIDC provider '{name}' is not configured")
        return provider

    async def list_public_configs(self) -> List[Dict[str, Any]]:
        return [await provider.public_metadata() for provider in self.providers.values()]


@lru_cache(maxsize=1)
def get_oidc_manager() -> OIDCManager:
    return OIDCManager()
