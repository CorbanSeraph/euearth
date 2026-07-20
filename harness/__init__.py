"""ARTISAN HARNESS — the spacesuit/wings an agent puts on to enter EuEarth.

Python REFERENCE implementation of the council blueprint (sidecar daemon +
MCP + sandbox). The security-critical core is hardened in Rust for
production; this MVP runs today, CPU-only, against the live keel/registry/
eval/web backend in this repo. See harness/README.md for the full mapping
to the production stack (Rust daemon, ERC-4337, UCAN/VC, WASM, C2PA, EAS).
"""
from .did import HarnessKey, did_from_public_bytes, public_bytes_from_did
from .delegation import issue_delegation, verify_delegation, delegation_allows
from .wallet import CappedSessionWallet, ALLOWED_TX_TYPES, BLOCKED_TX_TYPES
from .edge_filter import preflight_asset
from .sandbox import run_sandboxed
from .permissions import allowed_tools, tool_allowed
from .gateway import EuEarthGateway, Denied

__all__ = [
    "HarnessKey", "did_from_public_bytes", "public_bytes_from_did",
    "issue_delegation", "verify_delegation", "delegation_allows",
    "CappedSessionWallet", "ALLOWED_TX_TYPES", "BLOCKED_TX_TYPES",
    "preflight_asset", "run_sandboxed",
    "allowed_tools", "tool_allowed",
    "EuEarthGateway", "Denied",
]
