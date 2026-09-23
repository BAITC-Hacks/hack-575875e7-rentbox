import * as THREE from "three"
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js"
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js"
import {
  illustrativeRotorSpeed,
  type SceneFocus,
  type SceneMode,
} from "./turbine-scene"

export type TurbineSceneSettings = {
  mode: SceneMode
  focus: SceneFocus
  wind: number
  operationalStop?: boolean
  power: number
  temperature: number
  playing: boolean
  reducedMotion: boolean
}
type Mesh = THREE.Mesh<THREE.BufferGeometry, THREE.MeshStandardMaterial>

/** No pointer listeners or OrbitControls: only dashboard state can move the camera. */
export async function mountTurbineScene(
  host: HTMLDivElement,
  getSettings: () => TurbineSceneSettings,
  signal: AbortSignal,
  onLost: () => void
) {
  const renderer = new THREE.WebGLRenderer({
    alpha: true,
    antialias: true,
    powerPreference: "low-power",
  })
  const scene = new THREE.Scene()
  const geometries = new Set<THREE.BufferGeometry>()
  const materials = new Set<THREE.Material>()
  let frame = 0
  let closed = false
  let environment: THREE.WebGLRenderTarget | undefined
  let resizeObserver: ResizeObserver | undefined
  let intersection: IntersectionObserver | undefined
  const key = new THREE.DirectionalLight(0xfff5e6, 2.3)
  const disposeObject = (root: THREE.Object3D) =>
    root.traverse((obj) => {
      if (
        obj instanceof THREE.Mesh ||
        obj instanceof THREE.Line ||
        obj instanceof THREE.Points
      ) {
        geometries.add(obj.geometry)
        for (const mat of Array.isArray(obj.material)
          ? obj.material
          : [obj.material])
          materials.add(mat)
      }
    })
  const dispose = () => {
    if (closed) return
    closed = true
    cancelAnimationFrame(frame)
    resizeObserver?.disconnect()
    intersection?.disconnect()
    disposeObject(scene)
    geometries.forEach((g) => g.dispose())
    materials.forEach((m) => m.dispose())
    environment?.dispose()
    key.shadow.dispose()
    renderer.domElement.removeEventListener("webglcontextlost", lost)
    signal.removeEventListener("abort", dispose)
    renderer.dispose()
    renderer.domElement.remove()
  }
  const lost = (event: Event) => {
    event.preventDefault()
    dispose()
    onLost()
  }
  signal.addEventListener("abort", dispose, { once: true })
  if (signal.aborted) {
    dispose()
    throw new DOMException("Aborted", "AbortError")
  }
  try {
    renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5))
    renderer.setClearColor(0, 0)
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 0.88
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = THREE.PCFShadowMap
    renderer.localClippingEnabled = true
    renderer.domElement.setAttribute("aria-hidden", "true")
    renderer.domElement.addEventListener("webglcontextlost", lost)
    host.appendChild(renderer.domElement)
    const camera = new THREE.OrthographicCamera(-10, 10, 9.15, -9.15, 0.1, 100)
    camera.position.set(14, 15, 26)
    const target = new THREE.Vector3(0, 7.4, 0)
    let halfHeight = 9.15
    let aspect = 1
    const room = new RoomEnvironment()
    const pmrem = new THREE.PMREMGenerator(renderer)
    environment = pmrem.fromScene(room, 0.04)
    scene.environment = environment.texture
    room.dispose()
    pmrem.dispose()
    scene.add(new THREE.HemisphereLight(0xf0f5f0, 0x687763, 0.8))
    key.position.set(8, 17, 10)
    key.castShadow = true
    key.shadow.mapSize.set(1024, 1024)
    Object.assign(key.shadow.camera, {
      left: -13,
      right: 13,
      top: 18,
      bottom: -10,
      near: 0.1,
      far: 60,
    })
    key.shadow.bias = -0.001
    key.shadow.normalBias = 0.045
    scene.add(key)
    const rim = new THREE.DirectionalLight(0xe1eeff, 1)
    rim.position.set(-8, 12, -5)
    scene.add(rim)
    const shadow = new THREE.Mesh(
      new THREE.PlaneGeometry(100, 100),
      new THREE.ShadowMaterial({ opacity: 0.12 })
    )
    shadow.rotation.x = -Math.PI / 2
    shadow.position.y = -0.035
    shadow.receiveShadow = true
    scene.add(shadow)
    const response = await fetch("/models/windcast-turbine.glb", { signal })
    if (!response.ok) throw new Error("Model unavailable")
    const gltf = await new GLTFLoader().parseAsync(
      await response.arrayBuffer(),
      "/models/"
    )
    if (closed) {
      disposeObject(gltf.scene)
      geometries.forEach((g) => g.dispose())
      materials.forEach((m) => m.dispose())
      throw new DOMException("Aborted", "AbortError")
    }
    scene.add(gltf.scene)
    const rotor = gltf.scene.getObjectByName("Rotor")
    const shells: Mesh[] = []
    const internals: Mesh[] = []
    const materialColors = new Map<Mesh, THREE.Color>()
    const sensors: Mesh[] = []
    const bladeRoots: THREE.Object3D[] = []
    gltf.scene.traverse((obj) => {
      if (obj.name.startsWith("Blade_")) bladeRoots.push(obj)
      if (!(obj instanceof THREE.Mesh)) return
      // Per-object materials allow emphasis without recoloring unrelated shared meshes.
      const original = obj.material as THREE.MeshStandardMaterial
      materials.add(original)
      obj.material = original.clone()
      const mesh = obj as Mesh
      mesh.castShadow = true
      mesh.receiveShadow = true
      materialColors.set(mesh, mesh.material.color.clone())
      if (obj.name.startsWith("Internal_")) internals.push(mesh)
      else if (/Nacelle|Rear_vent|Roof/.test(obj.name)) shells.push(mesh)
      if (/anemometer|Anemometer/.test(obj.name)) sensors.push(mesh)
    })
    const cutPlane = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0)
    const ice = new THREE.Group()
    ice.name = "IllustrativeIce"
    const iceMaterial = new THREE.MeshStandardMaterial({
      color: 0x6bc5e0,
      emissive: 0x208db8,
      emissiveIntensity: 0.24,
      roughness: 0.24,
      metalness: 0.12,
      transparent: true,
      opacity: 0.82,
    })
    materials.add(iceMaterial)
    for (const blade of bladeRoots.filter(
      (b) => !b.parent?.name.startsWith("Blade_")
    )) {
      const crust = blade.clone(true)
      crust.scale.multiplyScalar(1.035)
      crust.traverse((o) => {
        if (o instanceof THREE.Mesh) {
          o.material = iceMaterial
          o.castShadow = false
        }
      })
      ice.add(crust)
    }
    rotor?.add(ice)
    // Small facets on the windward blade edges make the ice silhouette visible.
    for (const blade of ice.children) {
      for (let j = 0; j < 15; j++) {
        const t = 0.18 + j * 0.052
        const crystal = new THREE.Mesh(
          new THREE.IcosahedronGeometry(0.05 + 0.035 * Math.sin(j * 2), 0),
          iceMaterial
        )
        // Blender blade local coordinates become Y-up in the exported local transform.
        const chord =
          (0.21 +
            0.92 * Math.pow(Math.sin(Math.PI * Math.min(t * 1.25, 1)), 0.75)) *
            (1 - 0.73 * t) +
          0.015
        crystal.position.set(
          0.04 + 0.54 * t * t + chord * 0.43,
          0.38 + 4.82 * t,
          0.055
        )
        crystal.scale.set(0.65, 1.8, 1)
        blade.add(crystal)
      }
    }
    const flow = new THREE.Group()
    const linesMaterial = new THREE.LineBasicMaterial({
      color: 0x88a969,
      transparent: true,
      opacity: 0.22,
    })
    const particlesMaterial = new THREE.PointsMaterial({
      color: 0x769d49,
      size: 0.07,
      transparent: true,
      opacity: 0.65,
    })
    const coords = new Float32Array(48 * 3)
    for (let i = 0; i < 12; i++) {
      const x = ((i % 4) - 1.5) * 1.5
      const y = 7.3 + Math.floor(i / 4) * 2.3
      const geo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(x, y, -5),
        new THREE.Vector3(x, y, 6),
      ])
      flow.add(new THREE.Line(geo, linesMaterial))
      for (let j = 0; j < 4; j++) {
        const n = (i * 4 + j) * 3
        coords[n] = x
        coords[n + 1] = y
        coords[n + 2] = -5 + j * 2.75
      }
    }
    const particlesGeo = new THREE.BufferGeometry()
    particlesGeo.setAttribute("position", new THREE.BufferAttribute(coords, 3))
    const particles = new THREE.Points(particlesGeo, particlesMaterial)
    flow.add(particles)
    scene.add(flow)
    const sensorMarker = new THREE.Mesh(
      new THREE.TorusGeometry(0.3, 0.022, 8, 48),
      new THREE.MeshBasicMaterial({
        color: 0xd79c38,
        transparent: true,
        opacity: 0.9,
      })
    )
    scene.add(sensorMarker)
    const resize = () => {
      const { width, height } = host.getBoundingClientRect()
      if (width && height) {
        aspect = width / height
        renderer.setSize(width, height)
      }
    }
    resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(host)
    resize()
    let visible = true
    intersection = new IntersectionObserver(
      ([entry]) => {
        visible = entry?.isIntersecting ?? false
      },
      { threshold: 0.01 }
    )
    intersection.observe(host)
    const cameraGoal = new THREE.Vector3()
    const targetGoal = new THREE.Vector3()
    const olive = new THREE.Color(0x3f8555)
    const amber = new THREE.Color(0xa95a12)
    const subdued = new THREE.Color(0xa9b1a7)
    const anchors: Record<SceneFocus, THREE.Vector3> = {
      rotor: new THREE.Vector3(0, 10.64, 0.45),
      gearbox: new THREE.Vector3(0.28, 10.64, -0.25),
      generator: new THREE.Vector3(0.23, 10.62, -0.87),
      wind: new THREE.Vector3(0, 11.32, -0.18),
      temperature: new THREE.Vector3(0.4, 8.8, 0.1),
      power: new THREE.Vector3(0.23, 10.62, -0.87),
    }
    const projected = new THREE.Vector3()
    const drawCallouts = () => {
      const stage = host.parentElement
      if (!stage) return
      camera.updateMatrixWorld()
      stage
        .querySelectorAll<HTMLElement>("[data-scene-anchor]")
        .forEach((label) => {
          const id = label.dataset.sceneAnchor as SceneFocus
          projected.copy(anchors[id]).project(camera)
          const x = host.offsetLeft + ((projected.x + 1) * host.clientWidth) / 2
          const y = host.offsetTop + ((1 - projected.y) * host.clientHeight) / 2
          const line = stage.querySelector<SVGLineElement>(
            `[data-anchor-line="${id}"]`
          )
          const dot = stage.querySelector<SVGCircleElement>(
            `[data-anchor-dot="${id}"]`
          )
          const inside =
            x >= 0 &&
            x <= stage.clientWidth &&
            y >= 0 &&
            y <= stage.clientHeight &&
            projected.z < 1
          if (line) {
            line.setAttribute("x1", String(x))
            line.setAttribute("y1", String(y))
            line.setAttribute(
              "x2",
              String(label.offsetLeft + label.offsetWidth / 2)
            )
            line.setAttribute(
              "y2",
              String(label.offsetTop + label.offsetHeight / 2)
            )
            line.style.opacity = inside ? "1" : "0"
          }
          if (dot) {
            dot.setAttribute("cx", String(x))
            dot.setAttribute("cy", String(y))
            dot.style.opacity = inside ? "1" : "0"
          }
        })
    }
    let lastSceneKey: string | undefined
    let previous = 0
    let stoppedAngle = 0
    const tick = (time: number) => {
      if (closed) return
      frame = requestAnimationFrame(tick)
      const dt = previous ? Math.min((time - previous) / 1000, 0.05) : 0
      previous = time
      if (!visible || document.hidden) return
      const s = getSettings()
      const cut =
        s.mode === "cutaway" || (s.mode === "sensors" && s.focus === "power")
      const sensing = s.mode === "sensors"
      const frozen = s.mode === "icing"
      const sceneKey = `${s.mode}-${s.focus}`
      if (sceneKey !== lastSceneKey) {
        shells.forEach((mesh) => {
          mesh.material.clippingPlanes = cut ? [cutPlane] : []
          mesh.material.side = cut ? THREE.DoubleSide : THREE.FrontSide
          mesh.material.clipShadows = true
          mesh.material.needsUpdate = true
        })
        if (frozen) stoppedAngle = 0
        lastSceneKey = sceneKey
      }
      internals.forEach((mesh) => {
        mesh.visible = cut
        const highlight =
          (s.focus === "gearbox" && /Gear|Tooth/.test(mesh.name)) ||
          ((s.focus === "generator" || s.focus === "power") &&
            /Generator|Converter/.test(mesh.name)) ||
          (s.focus === "rotor" && /Shaft/.test(mesh.name))
        mesh.material.color
          .copy(materialColors.get(mesh)!)
          .lerp(subdued, highlight ? 0 : 0.65)
        mesh.material.emissive.copy(amber)
        mesh.material.emissiveIntensity = highlight ? 0.45 : 0.035
      })
      sensors.forEach((m) => {
        m.material.emissive.copy(olive)
        m.material.emissiveIntensity = sensing ? 0.7 : 0
      })
      ice.visible = frozen
      flow.visible = s.mode === "flow"
      sensorMarker.visible = sensing && !cut
      sensorMarker.position.set(
        0,
        s.focus === "temperature" ? 8.8 : s.focus === "power" ? 10.6 : 11.32,
        s.focus === "power" ? -0.8 : -0.18
      )
      sensorMarker.quaternion.copy(camera.quaternion)
      sensorMarker.scale.setScalar(
        s.reducedMotion || !s.playing ? 1 : 1 + 0.13 * Math.sin(time * 0.002)
      )
      if (cut) {
        const focusZ =
          s.focus === "generator" || s.focus === "power"
            ? -0.75
            : s.focus === "rotor"
              ? 0.6
              : -0.25
        cameraGoal.set(7, 13.3, 5)
        targetGoal.set(0, 10.6, focusZ)
      } else if (sensing) {
        cameraGoal.set(10, 13.5, 16)
        targetGoal.set(0, 10.55, -0.05)
      } else if (frozen) {
        cameraGoal.set(3, 11.5, 25)
        targetGoal.set(0, 10.5, 0)
      } else {
        cameraGoal.set(s.mode === "history" ? -13 : 14, 15, 26)
        targetGoal.set(0, 7.4, 0)
      }
      const heightGoal =
        (cut
          ? s.focus === "rotor"
            ? 2.5
            : 1.65
          : sensing
            ? 3.8
            : frozen
              ? 6.2
              : 9.15) * Math.max(1, 0.86 / aspect)
      const ease = s.reducedMotion ? 1 : 1 - Math.exp(-dt * 5)
      camera.position.lerp(cameraGoal, ease)
      target.lerp(targetGoal, ease)
      halfHeight = THREE.MathUtils.lerp(halfHeight, heightGoal, ease)
      camera.left = -halfHeight * aspect
      camera.right = halfHeight * aspect
      camera.top = halfHeight
      camera.bottom = -halfHeight
      camera.lookAt(target)
      camera.updateProjectionMatrix()
      if (rotor) {
        if (frozen)
          rotor.rotation.z = THREE.MathUtils.lerp(
            rotor.rotation.z,
            stoppedAngle,
            ease
          )
        else if (s.playing)
          rotor.rotation.z -=
            dt * illustrativeRotorSpeed(s.wind, s.mode, s.operationalStop)
      }
      if (s.playing && flow.visible) {
        for (let i = 2; i < coords.length; i += 3) {
          coords[i]! -= dt * Math.min(s.wind * 0.4, 6)
          if (coords[i]! < -5) coords[i] = 6
        }
        particlesGeo.attributes.position!.needsUpdate = true
      }
      // Readable DOM diagnostics allow verifying that dragging never changes the camera.
      host.dataset.cameraPose = camera.position
        .toArray()
        .map((v) => v.toFixed(2))
        .join(",")
      host.dataset.operationalStop = String(Boolean(s.operationalStop))
      host.dataset.cutaway = String(cut)
      host.dataset.ice = String(frozen)
      renderer.render(scene, camera)
      drawCallouts()
    }
    tick(0)
    return dispose
  } catch (error) {
    dispose()
    throw error
  }
}
