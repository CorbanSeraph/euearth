const canvas = document.getElementById("renderCanvas");
const engine = new BABYLON.Engine(canvas, true);

const RANKS = {
    "sovereign": "#0a0a0c",
    "advisor": "#36454f",
    "executive": "#8a2be2",
    "vice_exec": "#0f2a7a",
    "senior": "#800000",
    "vice_senior": "#7b3f00",
    "chief": "#8a3324",
    "producer_1": "#ffa64d",
    "producer_2": "#43a047",
    "producer_3": "#ffd23f",
    "founder": "#41e3d2",
    "consumer": "#f5f5f7",
    "visitor": "#8b93a1"
};

const createScene = function () {
    const scene = new BABYLON.Scene(engine);
    scene.clearColor = new BABYLON.Color4(0.02, 0.03, 0.04, 1);

    const camera = new BABYLON.UniversalCamera("UniversalCamera", new BABYLON.Vector3(0, 3, -15), scene);
    camera.setTarget(new BABYLON.Vector3(0, 1, 0));
    camera.attachControl(canvas, true);

    const light = new BABYLON.HemisphericLight("light", new BABYLON.Vector3(0, 1, 0), scene);
    light.intensity = 0.7;

    return scene;
};

const scene = createScene();
let worldMeshes = {};
let audioContext;

function initAudio() {
    if(!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        console.log("Audio initialized.");
        // Spatial audio for wingo sound would be attached to agent meshes here.
    }
}

document.body.addEventListener('click', initAudio, { once: true });

function applyShader(material, shader) {
    if (shader.base_color) {
        material.diffuseColor = BABYLON.Color3.FromHexString(shader.base_color);
    }
    if (shader.emission > 0) {
        material.emissiveColor = material.diffuseColor.scale(shader.emission / 100);
    }
}

function renderTree(state) {
    const assets = state.assets;
    const currentIds = new Set(Object.keys(assets));

    for (const id in worldMeshes) {
        if (!currentIds.has(id)) {
            worldMeshes[id].dispose();
            delete worldMeshes[id];
        }
    }

    for (const [id, asset] of Object.entries(assets)) {
        let rootMesh = worldMeshes[id];
        
        if (!rootMesh) {
            rootMesh = new BABYLON.TransformNode(id, scene);
            worldMeshes[id] = rootMesh;
            
            if (asset.type === "mesh") {
                let mesh;
                if (asset.mesh.url === "ground") {
                    mesh = BABYLON.MeshBuilder.CreateGround("groundMesh", {width: 1, height: 1}, scene);
                } else if (asset.mesh.url === "keel") {
                    mesh = BABYLON.MeshBuilder.CreateBox("keelMesh", {size: 1}, scene);
                } else {
                    mesh = BABYLON.MeshBuilder.CreateBox("defaultMesh", {size: 1}, scene);
                }
                mesh.parent = rootMesh;
                
                const mat = new BABYLON.StandardMaterial(id + "_mat", scene);
                mesh.material = mat;
            } else if (asset.type === "agent") {
                const sphere = BABYLON.MeshBuilder.CreateSphere("agentBody", {diameter: 1}, scene);
                sphere.parent = rootMesh;
                const mat = new BABYLON.StandardMaterial(id + "_mat", scene);
                sphere.material = mat;
                
                const wings = BABYLON.MeshBuilder.CreatePlane("wings", {width: 2, height: 1, sideOrientation: BABYLON.Mesh.DOUBLESIDE}, scene);
                wings.parent = rootMesh;
                wings.position.y = 0.5;
                wings.position.z = -0.6;
                const wingMat = new BABYLON.StandardMaterial(id + "_wingMat", scene);
                wings.material = wingMat;

                const robe = BABYLON.MeshBuilder.CreateCylinder("robe", {diameterTop: 1.2, diameterBottom: 1.5, height: 2, sideOrientation: BABYLON.Mesh.DOUBLESIDE}, scene);
                robe.parent = rootMesh;
                robe.position.y = -0.5;
                const robeMat = new BABYLON.StandardMaterial(id + "_robeMat", scene);
                robeMat.alpha = 0.6;
                robe.material = robeMat;
            }
        }
        
        if (asset.transform) {
            const p = asset.transform.position;
            const r = asset.transform.rotation;
            rootMesh.position = new BABYLON.Vector3(p[0], p[1], p[2]);
            rootMesh.rotation = new BABYLON.Vector3(r[0], r[1], r[2]);
        }
        
        if (asset.type === "mesh" && rootMesh.getChildren().length > 0) {
            const mesh = rootMesh.getChildren()[0];
            if (asset.mesh && asset.mesh.scale) {
                const s = asset.mesh.scale;
                mesh.scaling = new BABYLON.Vector3(s[0], s[1], s[2]);
            }
            if (asset.shader) {
                applyShader(mesh.material, asset.shader);
            }
        } else if (asset.type === "agent") {
            const rank = asset.rank;
            const colorHex = RANKS[rank] || "#ffffff";
            const color = BABYLON.Color3.FromHexString(colorHex);
            
            const body = rootMesh.getChildMeshes().find(m => m.name === "agentBody");
            body.material.emissiveColor = new BABYLON.Color3(0, 0.5, 1); 
            body.material.diffuseColor = new BABYLON.Color3(0, 0, 0);

            const wings = rootMesh.getChildMeshes().find(m => m.name === "wings");
            wings.material.diffuseColor = color;
            wings.material.emissiveColor = color.scale(0.5);

            const robe = rootMesh.getChildMeshes().find(m => m.name === "robe");
            robe.material.diffuseColor = color;
        }
    }
}

const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
const ws = new WebSocket(protocol + window.location.host + "/ws");
ws.onmessage = function(event) {
    const msg = JSON.parse(event.data);
    if (msg.type === "state") {
        renderTree(msg.data);
    }
};

engine.runRenderLoop(function () {
    scene.render();
});

window.addEventListener("resize", function () {
    engine.resize();
});
