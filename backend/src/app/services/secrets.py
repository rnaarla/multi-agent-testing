"""Secrets management abstraction for multi-environment deployments."""

from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SecretBackend(ABC):
    """Interface every secret backend must implement."""

    @abstractmethod
    def get_secret(self, name: str) -> Optional[str]:
        raise NotImplementedError


class EnvSecretBackend(SecretBackend):
    """Fallback backend that reads secrets from environment variables."""

    def get_secret(self, name: str) -> Optional[str]:
        direct = os.getenv(name)
        if direct:
            return direct
        env_key = name.upper().replace("/", "_").replace("-", "_")
        return os.getenv(env_key)


class AWSSecretBackend(SecretBackend):  # pragma: no cover - optional dependency
    """AWS Secrets Manager backend."""

    def __init__(self):  # pragma: no cover - optional dependency
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - optional dep
            raise RuntimeError("boto3 is required for AWS secret backend") from exc

        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        if not region:
            raise RuntimeError("AWS_REGION or AWS_DEFAULT_REGION must be set for AWS secret backend")
        self.client = boto3.client("secretsmanager", region_name=region)

    def get_secret(self, name: str) -> Optional[str]:  # pragma: no cover - optional dependency
        try:
            response = self.client.get_secret_value(SecretId=name)
        except Exception as exc:  # pragma: no cover - upstream error
            logger.error("Failed to fetch secret %s from AWS Secrets Manager", name, exc_info=exc)
            return None

        secret_string = response.get("SecretString")
        if secret_string:
            return secret_string
        binary_secret_data = response.get("SecretBinary")
        if binary_secret_data:
            return binary_secret_data.decode()
        return None


class GCPSecretBackend(SecretBackend):  # pragma: no cover - optional dependency
    """Google Secret Manager backend."""

    def __init__(self):  # pragma: no cover - optional dependency
        try:
            from google.cloud import secretmanager  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dep
            raise RuntimeError("google-cloud-secret-manager is required for GCP secret backend") from exc

        project = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise RuntimeError("GCP_PROJECT must be set for GCP secret backend")
        self.project = project
        self.client = secretmanager.SecretManagerServiceClient()

    def _resource_name(self, name: str) -> str:  # pragma: no cover - optional dependency
        if name.startswith("projects/"):
            return name
        return f"projects/{self.project}/secrets/{name}/versions/latest"

    def get_secret(self, name: str) -> Optional[str]:  # pragma: no cover - optional dependency
        try:
            response = self.client.access_secret_version(name=self._resource_name(name))
            payload = response.payload.data.decode("UTF-8")
            return payload
        except Exception as exc:  # pragma: no cover - upstream error
            logger.error("Failed to fetch secret %s from Google Secret Manager", name, exc_info=exc)
            return None


class VaultSecretBackend(SecretBackend):  # pragma: no cover - optional dependency
    """HashiCorp Vault backend for KV v2 secrets."""

    def __init__(self):  # pragma: no cover - optional dependency
        try:
            import hvac  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dep
            raise RuntimeError("hvac is required for Vault secret backend") from exc

        url = os.getenv("VAULT_ADDR")
        token = os.getenv("VAULT_TOKEN")
        if not url or not token:
            raise RuntimeError("VAULT_ADDR and VAULT_TOKEN must be set for Vault secret backend")
        self.mount_path = os.getenv("VAULT_KV_MOUNT", "secret")
        self.client = hvac.Client(url=url, token=token)

    def get_secret(self, name: str) -> Optional[str]:  # pragma: no cover - optional dependency
        path = name.lstrip("/")
        mount = self.mount_path.rstrip("/")
        try:
            response = self.client.secrets.kv.v2.read_secret_version(path=path, mount_point=mount)
        except Exception as exc:  # pragma: no cover - upstream error
            logger.error("Failed to fetch secret %s from Vault", name, exc_info=exc)
            return None
        data = response.get("data", {}).get("data")
        if isinstance(data, dict):
            return json.dumps(data)
        return None


def _build_backend() -> SecretBackend:
    backend_name = os.getenv("SECRET_BACKEND", "env").lower()
    try:
        if backend_name == "aws":
            return AWSSecretBackend()
        if backend_name == "gcp":
            return GCPSecretBackend()
        if backend_name == "vault":
            return VaultSecretBackend()
    except Exception as exc:
        logger.error("Falling back to env backend: %s", exc)
    return EnvSecretBackend()


class SecretManager:
    """High-level cache-aware secret accessor."""

    def __init__(self, backend: Optional[SecretBackend] = None, cache_ttl: Optional[int] = None):
        self.backend = backend or _build_backend()
        self.cache_ttl = cache_ttl or int(os.getenv("SECRET_CACHE_TTL_SECONDS", "300"))
        self._cache: Dict[str, Dict[str, Any]] = {}

    def get_secret(
        self,
        name: str,
        default: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Optional[str]:
        if not name:
            return default
        now = time.time()
        cached = self._cache.get(name)
        if cached and not force_refresh and now - cached["ts"] < self.cache_ttl:
            return cached["value"]

        value = self.backend.get_secret(name)
        if value is None:
            value = default
        self._cache[name] = {"value": value, "ts": now}
        return value

    def get_secret_json(
        self,
        name: str,
        default: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        raw = self.get_secret(name)
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Secret %s is not valid JSON", name)
            return default


_secret_manager: Optional[SecretManager] = None


def get_secret_manager() -> SecretManager:
    global _secret_manager
    if _secret_manager is None:
        _secret_manager = SecretManager()
    return _secret_manager


def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    return get_secret_manager().get_secret(name, default=default)


def resolve_provider_api_key(
    provider: str,
    default_env_var: str,
    explicit: Optional[str] = None,
) -> Optional[str]:
    if explicit:
        return explicit
    secret_name = f"providers/{provider}/api_key"
    env_default = os.getenv(default_env_var)
    return get_secret(secret_name, env_default)