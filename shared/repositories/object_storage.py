from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any

import boto3
from botocore.config import Config as BotocoreConfig

from shared.domain import AssetType


def generate_blob_ref(asset_type: AssetType) -> str:
    """Generate a unique storage key for one upload.

    Format: {asset_type}/{uuid4}.{ext}
    Generated once per upload — independent of temporal window.
    The same blob_ref is shared across split rows that reference the same content.
    """
    ext = "npy" if asset_type in (AssetType.DARKFRAME, AssetType.GRAYFRAME) else "json"
    return f"{asset_type}/{uuid.uuid4()}.{ext}"


class ObjectStorageRepository(ABC):
    @abstractmethod
    def put_object(self, key: str, content: bytes) -> str: ...

    @abstractmethod
    def generate_presigned_url(self, blob_ref: str, expires_in_seconds: int) -> str: ...


class ObjectStorageRepositoryS3(ObjectStorageRepository):
    def __init__(
        self,
        bucket: str,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        public_url: str = "",
    ) -> None:
        self._bucket = bucket
        self._endpoint_url = endpoint_url
        self._public_url = public_url or endpoint_url
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=BotocoreConfig(signature_version="s3v4"),
        )
        self._public_client: Any = boto3.client(
            "s3",
            endpoint_url=self._public_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=BotocoreConfig(signature_version="s3v4"),
        )

    def put_object(self, key: str, content: bytes) -> str:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=content)
        return key

    def generate_presigned_url(self, blob_ref: str, expires_in_seconds: int) -> str:
        return self._public_client.generate_presigned_url(  # type: ignore[no-any-return]
            "get_object",
            Params={"Bucket": self._bucket, "Key": blob_ref},
            ExpiresIn=expires_in_seconds,
        )
