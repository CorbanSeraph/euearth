import time
import jsonschema
from bender.tree import load_schema

ROTATION_CONSEQUENTIAL_THRESHOLD = 50

class MerlinGuard:
    def __init__(self, tree):
        self.tree = tree
        self.schema = load_schema("merlin_allowlist")
        self.edit_history = {}
        self.locks = {}
        self.witness_queue = []

    def process_mutation(self, did, mutation_payload):

        jsonschema.validate(instance=mutation_payload, schema=self.schema)

        target_id = mutation_payload["target_asset_id"]

        if target_id not in self.tree.assets:
            raise Exception(f"Target asset {target_id} not found in world tree.")
        
        target_asset = self.tree.assets[target_id]
        if target_asset.get("type") == "agent":
            raise Exception("MERLIN REJECT: Target asset may NEVER be an agent's own avatar/self.")

        now = time.time()
        if target_id in self.locks:
            if now < self.locks[target_id]:
                raise Exception(f"Asset {target_id} is locked due to an edit war. A rank-gated unlock is required.")
            else:
                del self.locks[target_id]

        history = self.edit_history.get(target_id, [])
        history = [record for record in history if now - record[0] < 10]
        history.append((now, did))
        self.edit_history[target_id] = history
        
        unique_dids = len(set([record[1] for record in history]))
        if unique_dids >= 5:
            self.locks[target_id] = now + 3600  # 1 hour expiry
            raise Exception("MERLIN LOCK ENGAGED: 5 differing DIDs edited within the window. Fail-closed.")
            
        if self._is_consequential(mutation_payload):
            self.witness_queue.append(mutation_payload)
            print(f"MERLIN: Consequential edit to {target_id} logged for witness review.")
            raise Exception("MERLIN REJECT: Consequential edit requires three-witness consensus. Hook not available.")

        self._apply(target_id, mutation_payload)

        return self.tree.get_state()

    def _apply(self, target_id, payload):
        asset = self.tree.assets[target_id]
        if "mesh" in payload:
            asset.setdefault("mesh", {}).update(payload["mesh"])
        if "shader" in payload:
            asset.setdefault("shader", {}).update(payload["shader"])
        if "transform" in payload:
            asset.setdefault("transform", {}).update(payload["transform"])
            
    def _is_consequential(self, payload):
        if "mesh" in payload and "scale" in payload["mesh"]:
            if any(abs(s) > 10 for s in payload["mesh"]["scale"]):
                return True
        if "transform" in payload:
            if "position" in payload["transform"] and any(abs(p) > 100 for p in payload["transform"]["position"]):
                return True
            if "rotation" in payload["transform"] and any(
                abs(r) > ROTATION_CONSEQUENTIAL_THRESHOLD
                for r in payload["transform"]["rotation"]
            ):
                return True
        return False
        
    def unlock(self, target_id, unlocked_by_rank):
        valid_ranks = ["sovereign", "advisor", "executive"]
        if unlocked_by_rank not in valid_ranks:
            raise Exception("Insufficient rank to unlock.")
        if target_id in self.locks:
            del self.locks[target_id]
        if target_id in self.edit_history:
            self.edit_history[target_id] = []
