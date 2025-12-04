"""Artifact storage utilities for execution traces and logs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import boto3  # type: ignore
    from botocore.exceptions import BotoCoreError, ClientError  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    boto3 = None
    BotoCoreError = ClientError = Exception


class ArtifactStorage:
    """Persist execution artifacts to local disk or S3."""

    def __init__(
        self,
        backend: str = "local",
        base_dir: Optional[Path] = None,
        bucket: Optional[str] = None,
        prefix: str = "artifacts/",
    ) -> None:
        self.backend = backend
        self.base_dir = base_dir or Path("storage/artifacts")
        self.bucket = bucket
        self.prefix = prefix.strip("/") + "/" if prefix else ""
        if self.backend == "local":
            self.base_dir.mkdir(parents=True, exist_ok=True)
        elif self.backend == "s3" and (not boto3 or not bucket):
            raise RuntimeError("S3 artifact storage requires boto3 and bucket configuration")
        if self.backend == "s3" and boto3:
            self._s3 = boto3.client("s3")
        else:
            self._s3 = None

    @classmethod
    def from_env(cls) -> "ArtifactStorage":
        bucket = os.getenv("ARTIFACTS_S3_BUCKET")
        prefix = os.getenv("ARTIFACTS_S3_PREFIX", "artifacts/")
        storage_dir = Path(os.getenv("ARTIFACT_STORAGE_DIR", "storage/artifacts"))
        if bucket:
            return cls(backend="s3", bucket=bucket, prefix=prefix)
        return cls(backend="local", base_dir=storage_dir)

    def _local_path(self, run_id: int, name: str) -> Path:
        return self.base_dir / f"run_{run_id}_{name}.json"

    def save_json(self, run_id: int, name: str, payload: Dict[str, Any]) -> str:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if self.backend == "local":
            path = self._local_path(run_id, name)
            path.write_bytes(data)
            return str(path)
        # S3 path
        key = f"{self.prefix}run_{run_id}_{name}.json"
        try:
            assert self._s3 is not None
            self._s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType="application/json")
            return f"s3://{self.bucket}/{key}"
        except (BotoCoreError, ClientError) as exc:  # pragma: no cover - network
            raise RuntimeError(f"Failed to upload artifact to S3: {exc}")


artifact_storage = ArtifactStorage.from_env()
