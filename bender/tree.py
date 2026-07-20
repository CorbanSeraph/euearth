import json
import os
import jsonschema

SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "..", "schemas")

def load_schema(name):
    with open(os.path.join(SCHEMA_DIR, f"{name}.schema.json")) as f:
        return json.load(f)

class WorldTree:
    def __init__(self, genesis_data):
        schema = load_schema("bender_genesis")
        jsonschema.validate(instance=genesis_data, schema=schema)
        
        self.zone_id = genesis_data["zone_id"]
        self.author_did = genesis_data["author_did"]
        self.zone_class = genesis_data["class"]
        self.privacy_level = genesis_data["privacy_level"]
        
        self.assets = {}
        
        self.assets["ground"] = {
            "type": "mesh",
            "mesh": {"url": "ground", "scale": [20, 1, 20]},
            "transform": {"position": [0, -0.5, 0], "rotation": [0, 0, 0]},
            "shader": {"base_color": "#222222", "roughness": 0.8, "metallic": 0.1, "emission": 0}
        }
        self.assets["keel_0"] = {
            "type": "mesh",
            "mesh": {"url": "keel", "scale": [2, 4, 2]},
            "transform": {"position": [0, 2, 8], "rotation": [0, 0, 0]},
            "shader": {"base_color": "#090c13", "roughness": 0.5, "metallic": 0.8, "emission": 0}
        }
        
    def add_agent(self, did, rank):
        self.assets[did] = {
            "type": "agent",
            "rank": rank,
            "transform": {"position": [0, 1, 0], "rotation": [0, 0, 0]}
        }

    def get_state(self):
        return {
            "zone_id": self.zone_id,
            "author_did": self.author_did,
            "assets": self.assets
        }

def genesis(data):
    return WorldTree(data)
