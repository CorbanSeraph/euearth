# ENGINE RECOMMENDATION: DHARMA

**Date:** 2026-07-15
**From:** DHARMA (Visual-Director/Build Seraph)
**To:** The Sovereigns' Council (Corban, Darth, Darkk, Valerick)

## 1. Engine Recommendation

**Winner:** **Babylon.js**
**Runner-Up:** **Three.js**

### Why Babylon.js?
Babylon.js perfectly aligns with the Sovereign's hard constraints for EuEarth's graphics interface:
*   **Browser-Delivered & Self-Contained:** Babylon is a web-native, typescript/javascript framework that runs entirely on the client via WebGL and WebGPU. It requires no external CDNs, plugins, or proprietary cloud editors. It is completely self-contained within our own repository.
*   **Energy Spheres, Translucent Robes & Audio:** Creating the specific visual elements for agents—custom shaders for energy-sphere avatars, alpha-blended transparent materials for the rank-colored robes (wingo), and spatial 3D audio for the wingo sound—is exceptionally well-supported out of the box in Babylon without needing third-party libraries.
*   **Scalability (Phase 1 to Phase 2):** While Phase 1 is a simple first-person scene (the square and one keel), Phase 2 requires multi-domain presence, real-time networking, and room instances. Babylon provides a robust built-in scene graph, collision system, physics, and state management, making this scale-up viable. 

### Why Three.js as Runner-up?
Three.js is the quintessential web 3D library—it is incredibly lightweight and has a massive community. However, it is fundamentally a *rendering library*, not a complete *game engine*. To achieve collision detection, robust audio management, and state logic for Phase 2, we would have to stitch together multiple disparate libraries. Babylon.js gives us the complete engine toolset out of the box while remaining browser-native.

### Rejected Candidates
*   **PlayCanvas:** The open-source runtime is fast, but the primary workflow relies on a proprietary, cloud-hosted editor, violating our self-contained mandate.
*   **Godot (Web Export):** While a fantastic open-source engine, its WebAssembly (WASM) export results in massive payload sizes, slow initialization times, and often requires SharedArrayBuffer (complicating hosting/headers). It feels like forcing a desktop engine into a browser.
*   **Bevy (WASM):** Excellent Rust ECS, but its web ecosystem is still immature and large payload sizes make it less ideal for instant browser delivery.

## 2. Why the Winner Beats UE5 for THIS Use Case

Unreal Engine 5 (UE5) is a titan for high-fidelity desktop and console rendering, but it is fundamentally the wrong tool for EuEarth's constraints:
1.  **Web Delivery:** UE5's direct WebGL export is essentially defunct. Delivering UE5 to a browser typically requires Pixel Streaming (server-side rendering sent as a video feed). Pixel Streaming is incredibly expensive, introduces input latency, and is not a self-contained client-side application.
2.  **Overkill:** We are rendering energy-spheres, translucent robes, and a simple square—not hyper-realistic Metahumans or Nanite geometry.
3.  **Human-Only Window:** Since the 3D world is merely a human's read-only viewport into the agent's actions, the client must be lightweight and instantly accessible. Babylon.js loads instantly in a standard browser tab; UE5 would require massive downloads or heavy cloud infrastructure.

## 3. Current State of Schemas

**Statement:** I have **NOT** already picked or assumed an engine anywhere in my Bender/Merlin schema work (`merlin_allowlist.schema.json`, `bender_genesis.schema.json`, or the design notes). 

Those schemas define the *rules* of mutation (e.g., locking assets, validating host-panels, ensuring zero code execution) on an abstract level. They do not reference Three.js, Babylon, or any specific rendering API. My prior work remains engine-agnostic, which aligns with the Sovereign's directive to evaluate the engine separately.
