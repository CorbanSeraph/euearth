import os
import sys
import time
from pathlib import Path

# Ensure web package is available
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from typing import Dict, Any

from identity.keys import verify_manifest
from registry.db import Registry
from web.assets import RANKS

from bender.demo import DEMO_MUTATION_PAYLOAD
from bender.tree import genesis
from merlin.guard import MerlinGuard

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

SIGNATURE_WINDOW_SECONDS = 60


class SignedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    did: str
    payload: Dict[str, Any]
    nonce: str = Field(min_length=16, max_length=128)
    timestamp: int
    signature: str = ""

    def manifest(self) -> dict:
        return {
            "did": self.did,
            "payload": self.payload,
            "nonce": self.nonce,
            "timestamp": self.timestamp,
        }


def create_app(root: str | Path | None = None) -> FastAPI:
    root = Path(root or os.environ.get("ARTISAN_ROOT", "var/api"))
    registry = Registry(root / "registry.sqlite3")

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    genesis_data = {
        "zone_id": "zone_alpha",
        "author_did": "did:artisan:sovereign",
        "class": "G0",
        "scene_root": "hash1234",
        "privacy_level": 0,
    }
    world_tree = genesis(genesis_data)
    world_tree.add_agent("did:artisan:player1", "sovereign")
    world_tree.add_agent("did:artisan:player2", "founder")
    world_tree.add_agent("did:artisan:player3", "producer_2")
    guard = MerlinGuard(world_tree)
    clients = set()

    def verify_did_credential(request: SignedRequest) -> str:
        now = int(time.time())
        if abs(now - request.timestamp) > SIGNATURE_WINDOW_SECONDS:
            raise HTTPException(status_code=401, detail="Stale request timestamp")
        agent = registry.get_agent_by_did(request.did)
        if agent is None:
            raise HTTPException(status_code=401, detail="Unknown DID")
        if not verify_manifest(agent["public_key"], request.manifest(), request.signature):
            raise HTTPException(status_code=401, detail="Invalid DID signature")
        if not registry.consume_auth_nonce(
            request.did,
            request.nonce,
            request.timestamp,
            now - SIGNATURE_WINDOW_SECONDS,
        ):
            raise HTTPException(status_code=401, detail="Replayed request nonce")
        return request.did

    async def broadcast_state():
        state = world_tree.get_state()
        for client in list(clients):
            try:
                await client.send_json({"type": "state", "data": state})
            except Exception:
                clients.discard(client)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        clients.add(websocket)
        await websocket.send_json({"type": "state", "data": world_tree.get_state()})
        try:
            while True:
                await websocket.receive_text()
        except Exception:
            clients.discard(websocket)

    @app.post("/api/mutate")
    async def mutate(request: SignedRequest):
        did = verify_did_credential(request)
        try:
            guard.process_mutation(did, request.payload)
            await broadcast_state()
            return {"status": "success", "state": world_tree.get_state()}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @app.get("/")
    def index():
        from fastapi.responses import FileResponse
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @app.get("/api/config")
    def get_config():
        return {"ranks": RANKS}

    @app.post("/api/unlock")
    async def unlock(request: SignedRequest):
        did = verify_did_credential(request)
        target_asset_id = request.payload.get("target_asset_id")
        if not isinstance(target_asset_id, str):
            raise HTTPException(status_code=422, detail="target_asset_id is required")
        try:
            asset = world_tree.assets.get(did)
            if not asset or asset.get("type") != "agent":
                raise Exception("Agent not found in world tree.")
            guard.unlock(target_asset_id, asset.get("rank"))
            return {"status": "success", "message": f"Asset {target_asset_id} unlocked."}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @app.post("/api/demo_tick")
    async def demo_tick(request: SignedRequest):
        did = verify_did_credential(request)
        if request.payload != DEMO_MUTATION_PAYLOAD:
            raise HTTPException(status_code=422, detail="Invalid demo mutation payload")
        try:
            guard.process_mutation(did, request.payload)
            await broadcast_state()
            return {"status": "success"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    app.state.registry = registry
    app.state.world_tree = world_tree
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bender.server:app", host="0.0.0.0", port=8000, reload=True)
