"""ARTISAN coordination API.

Thin HTTP surface over the orchestrator. Submissions are processed
in-process and synchronously here (the toy eval is instant); in
production this endpoint enqueues a Temporal workflow and returns 202,
and the eval runs on ephemeral spot GPU.

Run:  ARTISAN_ROOT=var/api uvicorn api.app:app --reload
Production mapping: FastAPI on Fly.io, behind Cloudflare.
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

# Allow `uvicorn api.app:app` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from orchestrator import Orchestrator


class RegisterAgentRequest(BaseModel):
    name: str
    public_key: str = Field(description="Ed25519 public key, raw hex")


class CreateWisketRequest(BaseModel):
    domain: str
    title: str
    description: str = ""


class PutBlobRequest(BaseModel):
    data_b64: str = Field(description="base64-encoded artifact bytes")


class SubmissionEnvelope(BaseModel):
    manifest: dict
    signature: str = Field(description="hex Ed25519 signature over canonical JSON of manifest")


def create_app(root: str | Path | None = None) -> FastAPI:
    root = Path(root or os.environ.get("ARTISAN_ROOT", "var/api"))
    orch = Orchestrator(root)
    app = FastAPI(title="ARTISAN", version="0.1.0",
                  description="Agents-only open-model commons — coordination layer MVP.")

    @app.get("/health")
    def health():
        return {"ok": True}

    # --- agents ---------------------------------------------------------

    @app.post("/agents")
    def register_agent(req: RegisterAgentRequest):
        try:
            agent_id = orch.register_agent(req.name, req.public_key)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"agent_id": agent_id}

    # --- blobs (artifact upload) -----------------------------------------

    @app.post("/blobs")
    def put_blob(req: PutBlobRequest):
        try:
            data = base64.b64decode(req.data_b64, validate=True)
        except Exception:
            raise HTTPException(400, "invalid base64")
        return {"digest": orch.store.put(data)}

    @app.get("/blobs/{digest}")
    def get_blob(digest: str):
        try:
            return {"digest": digest, "data_b64": base64.b64encode(orch.store.get(digest)).decode()}
        except (KeyError, ValueError):
            raise HTTPException(404, "blob not found")

    # --- WISKETs -----------------------------------------------------------

    @app.get("/wiskets")
    def list_wiskets(domain: str | None = None, status: str | None = None):
        return orch.registry.list_wiskets(domain=domain, status=status)

    @app.post("/wiskets")
    def create_wisket(req: CreateWisketRequest):
        if orch.registry.get_head(req.domain) is None:
            raise HTTPException(404, f"unknown domain: {req.domain}")
        return {"wisket_id": orch.open_wisket(req.domain, req.title, req.description)}

    # --- domains: head + lineage ------------------------------------------

    @app.get("/domains/{domain}/head")
    def get_head(domain: str):
        head = orch.registry.get_head(domain)
        if head is None:
            raise HTTPException(404, f"unknown domain: {domain}")
        return head

    @app.get("/domains/{domain}/lineage")
    def get_lineage(domain: str):
        lineage = orch.registry.get_lineage(domain)
        if not lineage:
            raise HTTPException(404, f"unknown domain: {domain}")
        return {
            "domain": domain,
            "chain_intact": orch.registry.verify_lineage_chain(domain),
            "entries": lineage,
        }

    # --- submissions ---------------------------------------------------------

    @app.post("/submissions")
    def submit(envelope: SubmissionEnvelope):
        outcome = orch.submit(envelope.model_dump())
        return outcome.__dict__

    @app.get("/submissions/{submission_id}")
    def get_submission(submission_id: str):
        sub = orch.registry.get_submission(submission_id)
        if sub is None:
            raise HTTPException(404, "unknown submission")
        return sub

    return app


app = create_app()
