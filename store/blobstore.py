"""Content-addressed blob store.

Every artifact in ARTISAN (base spec, router config, expert adapters,
dataset manifests) is stored and referenced by the sha256 of its bytes.
Content addressing is what makes public mirrors safe: anyone can serve
the bits, the digest (plus a signature over the manifest that names the
digest) proves they are the canonical bits.

Production mapping: `LocalFSBlobStore` -> an `R2BlobStore` implementing
the same `BlobStore` interface against Cloudflare R2 (put via presigned
multipart upload, get via CDN). Nothing above this interface changes.
"""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from pathlib import Path


def sha256_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class BlobStore(ABC):
    """Interface for content-addressed storage. Keys ARE sha256 hex digests."""

    @abstractmethod
    def put(self, data: bytes) -> str:
        """Store bytes, return their sha256 hex digest."""

    @abstractmethod
    def get(self, digest: str) -> bytes:
        """Return the bytes for a digest. Raises KeyError if absent.

        Implementations MUST verify content integrity before returning."""

    @abstractmethod
    def has(self, digest: str) -> bool:
        """True if the digest is present."""

    # Convenience helpers shared by all backends -------------------------

    def put_json(self, obj) -> str:
        """Store an object as canonical JSON (sorted keys, tight separators).

        Canonical serialization means identical objects always yield the
        same digest, across machines and backends."""
        data = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return self.put(data)

    def get_json(self, digest: str):
        return json.loads(self.get(digest).decode("utf-8"))


class LocalFSBlobStore(BlobStore):
    """Filesystem backend. Layout: <root>/sha256/<d[:2]>/<d[2:4]>/<digest>."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, digest: str) -> Path:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"not a sha256 hex digest: {digest!r}")
        return self.root / "sha256" / digest[:2] / digest[2:4] / digest

    def put(self, data: bytes) -> str:
        digest = sha256_digest(data)
        path = self._path(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.rename(path)  # atomic on POSIX
        return digest

    def get(self, digest: str) -> bytes:
        path = self._path(digest)
        if not path.exists():
            raise KeyError(f"blob not found: {digest}")
        data = path.read_bytes()
        if sha256_digest(data) != digest:  # tamper / corruption check
            raise IOError(f"blob corrupted on disk: {digest}")
        return data

    def has(self, digest: str) -> bool:
        try:
            return self._path(digest).exists()
        except ValueError:
            return False
