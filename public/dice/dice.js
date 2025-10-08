import * as THREE from 'three'
import * as CANNON from 'cannon-es'
import CameraControls from 'camera-controls'
import { RGBELoader } from 'three/examples/jsm/loaders/RGBELoader.js'
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js'
import {
  DiceManager,
  DiceD4,
  DiceD6,
  DiceD8,
  DiceD10,
  DiceD12,
  DiceD20
} from 'threejs-dice'

CameraControls.install({ THREE })

/** Copied from https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Math/random#getting_a_random_number_between_two_values */
function getRandomArbitrary (min, max) {
  return Math.random() * (max - min) + min
}

const scene = new THREE.Scene()

// Initialize the renderer.
const renderer = new THREE.WebGLRenderer({ antialias: true })
renderer.setSize(window.innerWidth, window.innerHeight)
renderer.shadowMap.enabled = true
renderer.shadowMap.type = THREE.PCFSoftShadowMap
document.body.appendChild(renderer.domElement)

/* "The Cannon physics library is ideal for simulating rigid bodies." https://sbcode.net/threejs/physics-cannonjs/ */
const world = new CANNON.World()
world.gravity.set(0, -9.82 * 50, 0)
/* "Broad phase is the first step in the collision detection process, where it identifies which objects might be
    colliding. It's called broad phase because it uses bounding boxes that are aligned with the axes, and only reports
    potential collisions. The next step in the process, called narrow phase, is when the actual collisions are detected
    and resolved." (Gemini-generated)
    See https://pmndrs.github.io/cannon-es/docs/classes/Broadphase.html */
world.broadphase = new CANNON.NaiveBroadphase()
world.solver.iterations = 16

// Floor.
const floorBody = new CANNON.Body({
  mass: 0,
  shape: new CANNON.Plane(),
  material: DiceManager.floorBodyMaterial
})
floorBody.quaternion.setFromAxisAngle(new CANNON.Vec3(1, 0, 0), -Math.PI / 2)
world.addBody(floorBody)

DiceManager.setWorld(world)

const textureLoader = new THREE.TextureLoader()
function applyCommonSettingsToTextureMap (map) {
  map.wrapS = THREE.RepeatWrapping
  map.wrapT = THREE.RepeatWrapping
  map.anisotropy = 4
  map.repeat.set(1, 1)
  map.colorSpace = THREE.SRGBColorSpace
}
new RGBELoader().load(
  'https://cdn.glitch.global/76fe1fa3-d3aa-4d7b-911f-8ad91e01d136/studio_small_08_2k.hdr?v=1646042358774',
  (texture) => {
    texture.mapping = THREE.EquirectangularReflectionMapping
    scene.background = texture
    scene.environment = texture
  }
)
/* https://tympanus.net/codrops/2021/10/27/creating-the-effect-of-transparent-glass-and-plastic-in-three-js/ */
const materialOptions = {
  transmission: 1,
  thickness: 75,
  roughness: 0.25,
  ior: 1.5,
  /* Normal map makes the surface look rough.
     Source: https://opengameart.org/node/8180 */
  normalMap: textureLoader.load('public/dice/packeddirt_n.jpg'),
  // Add some scratches to the surface.
  clearcoatNormalMap: textureLoader.load(
    'https://threejs.org/examples/textures/pbr/Scratched_gold/Scratched_gold_01_1K_Normal.png',
    applyCommonSettingsToTextureMap
  ),
  clearcoat: 0.5,
  /* "In case the material has a normal map authored using the left handed convention, the y component of normalScale
     should be negated to compensate for the different handedness."
     https://threejs.org/docs/#api/en/materials/MeshPhongMaterial.normalScale */
  clearcoatNormalScale: new THREE.Vector2(1.0, -1.0)
}
const diceArray = []
diceOptions.forEach(([type, value], index) => {
  // eslint-disable-line no-undef
  let dice
  switch (type) {
    case 'd4':
      dice = new DiceD4({ materialOptions })
      break
    case 'd6':
      dice = new DiceD6({ materialOptions })
      break
    case 'd8':
      dice = new DiceD8({ materialOptions })
      break
    case 'd10':
      dice = new DiceD10({ materialOptions })
      break
    case 'd12':
      dice = new DiceD12({ materialOptions })
      break
    case 'd20':
      dice = new DiceD20({ materialOptions })
      break
    default:
      break
  }

  if (dice) {
    dice
      .getObject()
      .position.set(
        index * 200 + 100,
        200 + getRandomArbitrary(-100, 100),
        getRandomArbitrary(-100, 100)
      )
    // Ranges of Euler angles (ϕ,θ,ψ): [0,2π)×[−π/2,π/2]×[0,2π).
    // https://motion.cs.illinois.edu/RoboticSystems/3DRotations.html
    dice
      .getObject()
      .rotation.set(
        getRandomArbitrary(0, 2) * Math.PI,
        getRandomArbitrary(-0.5, 0.5) * Math.PI,
        getRandomArbitrary(0, 2) * Math.PI
      )

    dice.getObject().body.velocity.set(
      getRandomArbitrary(-100, 100),
      // Doesn't make sense to have an initial velocity going upwards.
      getRandomArbitrary(0, 100),
      getRandomArbitrary(-100, 100)
    )

    dice
      .getObject()
      .body.angularVelocity.set(
        getRandomArbitrary(-5, 5),
        getRandomArbitrary(-5, 5),
        getRandomArbitrary(-5, 5)
      )

    dice.updateBodyFromMesh()

    setTimeout(() => scene.add(dice.getObject()), index * 100 /* ms */)
    // We use `forEach` + `push` instead of `map`, because `dice` may be `undefined`.
    diceArray.push({ dice, value })
  }
})
DiceManager.prepareValues(diceArray)

// Initialize the camera. We see the scene through this camera.
// https://threejs.org/docs/#api/en/cameras/PerspectiveCamera
const camera = new THREE.PerspectiveCamera(
  45, // vertical field of view
  window.innerWidth / window.innerHeight, // aspect ratio
  0.1, // can see very near
  100000 // can see very far
)
camera.up = new THREE.Vector3(0, 1, 0)
scene.add(camera)

// Initialize camera controls, so that you can use your mouse on the scene to tilt & pan the camera.
const clock = new THREE.Clock()
const cameraControls = new CameraControls(camera, renderer.domElement)
// Use `cameraControls.setLookAt` instead of `camera.position` and `camera.lookAt`.
cameraControls.setLookAt(
  // sitting at...
  diceArray.length * 100,
  1000,
  500,
  // gazing at...
  diceArray.length * 100,
  100,
  100,
  false // Don't animate the transition.
)

/** We want to render a plane as the "ground" of our scene, where dices will bounce off and settle still.
   Note how this is different from the `floorBody` that we added to the Cannon.js world.
   The `ground` mesh is a visual representation of the ground, while the `floorBody` is a physical representation of the ground. */
function createGround () {
  const groundGeometry = new THREE.PlaneGeometry(
    // We want the ground to be wide enough to encompass all dices...
    diceArray.length * 300,
    // ... but still have a fixed height.
    800
  )
  // Create a material for the ground.
  const groundMaterial = new THREE.MeshPhysicalMaterial()
  /* I really like the wooden texture from the three.js examples, so I'm going to use it here.
       https://github.com/mrdoob/three.js/blob/master/examples/webgl_lights_physical.html */
  const baseUrl = 'https://threejs.org/examples/textures/hardwood2_'
  textureLoader.load(baseUrl + 'diffuse.jpg', (map) => {
    groundMaterial.map = map
    applyCommonSettingsToTextureMap(map)
  })
  textureLoader.load(baseUrl + 'bump.jpg', (map) => {
    groundMaterial.bumpMap = map
    applyCommonSettingsToTextureMap(map)
  })
  textureLoader.load(baseUrl + 'roughness.jpg', (map) => {
    groundMaterial.roughnessMap = map
    applyCommonSettingsToTextureMap(map)
  })

  const ground = new THREE.Mesh(groundGeometry, groundMaterial)
  scene.add(ground)
  ground.position.set(diceArray.length * 100, 0, 0)
  ground.rotation.set(-Math.PI / 2, 0, 0)
  ground.receiveShadow = true
  return ground
}
createGround()

/* Add Bloom effect to the scene.
  https://github.com/mrdoob/three.js/blob/37d6f280a5cd642e801469bb048f52300d31258e/examples/webgl_postprocessing_unreal_bloom.html */
const renderScene = new RenderPass(scene, camera)

const bloomPass = new UnrealBloomPass(
  new THREE.Vector2(window.innerWidth, window.innerHeight),
  1.5,
  0.4,
  0.85
)
bloomPass.threshold = 0.9
bloomPass.strength = 0.2
bloomPass.radius = 0

const outputPass = new OutputPass()

const composer = new EffectComposer(renderer)
composer.addPass(renderScene)
composer.addPass(bloomPass)
composer.addPass(outputPass)

function animate () {
  world.step(1.0 / 60.0)
  diceArray.forEach((diceObj) => {
    diceObj.dice.updateMeshFromBody()
  })

  const delta = clock.getDelta()
  cameraControls.update(delta)
  requestAnimationFrame(animate) // eslint-disable-line no-undef
  composer.render()
}

requestAnimationFrame(animate) // eslint-disable-line no-undef
