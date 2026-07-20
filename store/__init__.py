"""artisan.store — content-addressed blob storage.

Local filesystem backend today; the BlobStore interface is what a
Cloudflare R2 backend implements in production (same digests, same API).
"""
from .blobstore import BlobStore, LocalFSBlobStore, sha256_digest

__all__ = ["BlobStore", "LocalFSBlobStore", "sha256_digest"]
