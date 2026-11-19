import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'
import ForgeSceneFallback from './ForgeSceneFallback'

type ForgeSceneProps = {
  progress?: number
  scenario?: 'placement' | 'obstacles' | 'grip'
  paused?: boolean
}

/** An artistic illustration of an experiment, never a recorded robot rollout. */
export default function ForgeScene({ progress = 0, scenario = 'placement', paused = false }: ForgeSceneProps) {
  const mountRef = useRef<HTMLDivElement>(null)
  const inputs = useRef({ progress, scenario, paused })
  const wakeRef = useRef<(() => void) | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    inputs.current = { progress, scenario, paused }
    wakeRef.current?.()
  }, [progress, scenario, paused])

  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return
    let renderer: THREE.WebGLRenderer
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' })
    } catch {
      setFailed(true)
      return
    }

    let disposed = false
    let raf = 0
    let visible = true
    let lastFrame = 0
    let elapsed = 0
    let placementMix = inputs.current.scenario === 'placement' ? 1 : 0
    let obstacleMix = inputs.current.scenario === 'obstacles' ? 1 : 0
    let gripMix = inputs.current.scenario === 'grip' ? 1 : 0
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    let reduceMotion = mediaQuery.matches
    const pointer = new THREE.Vector2()
    const smoothPointer = new THREE.Vector2()
    const geometries = new Set<THREE.BufferGeometry>()
    const materials = new Set<THREE.Material>()
    const scene = new THREE.Scene()
    const camera = new THREE.OrthographicCamera(-2.7, 2.7, 2.3, -2.3, .1, 40)
    const target = new THREE.Vector3(.02, 1.20, 0)
    camera.position.set(4.8, 3.35, 7.3)
    camera.lookAt(target)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5))
    renderer.setClearColor(0x000000, 0)
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = THREE.PCFShadowMap
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.12
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.domElement.style.cssText = 'display:block;width:100%;height:100%;pointer-events:none;'
    renderer.domElement.setAttribute('aria-hidden', 'true')
    mount.appendChild(renderer.domElement)

    const pmrem = new THREE.PMREMGenerator(renderer)
    const environment = new RoomEnvironment()
    const environmentMap = pmrem.fromScene(environment, .04)
    scene.environment = environmentMap.texture
    scene.environmentIntensity = .36
    environment.dispose()
    pmrem.dispose()

    const mat = (color: string, roughness = .35, metalness = .1) => {
      const material = new THREE.MeshStandardMaterial({ color, roughness, metalness })
      materials.add(material)
      return material
    }
    const porcelain = mat('#bcc6c0', .26, .56)
    const porcelainEdge = mat('#6e8077', .25, .72)
    const graphite = mat('#111a17', .29, .56)
    const rubber = mat('#090e0c', .75, .05)
    const silver = mat('#91a99b', .22, .85)
    const orange = mat('#ff632b', .32, .24)
    const platformMat = mat('#1d2a24', .45, .55)
    const tabletopMat = mat('#233129', .48, .48)
    const floorMat = new THREE.ShadowMaterial({ color: '#000000', opacity: .4 })
    materials.add(floorMat)
    const orangeGlow = new THREE.MeshStandardMaterial({ color: '#ff672f', emissive: '#ff5722', emissiveIntensity: .8, roughness: .4 })
    materials.add(orangeGlow)
    const geometry = <T extends THREE.BufferGeometry>(value: T): T => {
      geometries.add(value)
      return value
    }
    const mesh = (shape: THREE.BufferGeometry, material: THREE.Material, parent: THREE.Object3D, position?: [number, number, number]) => {
      const object = new THREE.Mesh(geometry(shape), material)
      object.castShadow = true
      object.receiveShadow = true
      if (position) object.position.set(...position)
      parent.add(object)
      return object
    }
    const cylinder = (parent: THREE.Object3D, radius: number, height: number, material: THREE.Material, position: [number, number, number], radiusBottom = radius) =>
      mesh(new THREE.CylinderGeometry(radius, radiusBottom, height, 48), material, parent, position)
    const capsule = (parent: THREE.Object3D, start: THREE.Vector3, end: THREE.Vector3, radius: number, material: THREE.Material) => {
      const delta = end.clone().sub(start)
      const object = mesh(new THREE.CapsuleGeometry(radius, Math.max(.001, delta.length() - 2 * radius), 8, 32), material, parent)
      object.position.copy(start).add(end).multiplyScalar(.5)
      object.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.normalize())
      return object
    }
    const bolt = (parent: THREE.Object3D, x: number, y: number, z: number, radius = .026) => {
      const boltMesh = cylinder(parent, radius, .012, silver, [x, y, z])
      boltMesh.rotation.x = Math.PI / 2
      return boltMesh
    }
    const joint = (parent: THREE.Object3D, radius: number) => {
      const barrel = cylinder(parent, radius, radius * 1.7, graphite, [0, 0, 0])
      barrel.rotation.x = Math.PI / 2
      for (const side of [-1, 1]) {
        const cap = cylinder(parent, radius * .83, .045, porcelainEdge, [0, 0, side * radius * .86])
        cap.rotation.x = Math.PI / 2
        const inset = cylinder(parent, radius * .54, .052, graphite, [0, 0, side * radius * .88])
        inset.rotation.x = Math.PI / 2
        const center = cylinder(parent, radius * .27, .055, silver, [0, 0, side * radius * .9])
        center.rotation.x = Math.PI / 2
      }
      for (let i = 0; i < 4; i++) {
        const angle = i * Math.PI / 2 + Math.PI / 4
        bolt(parent, Math.cos(angle) * radius * .67, Math.sin(angle) * radius * .67, radius * .9, .018)
      }
    }

    const ambient = new THREE.HemisphereLight('#dbe9e1', '#0c1710', .8)
    scene.add(ambient)
    const key = new THREE.DirectionalLight('#eaf5ed', 5.2)
    key.position.set(-3, 7, 4)
    key.castShadow = true
    key.shadow.mapSize.set(1024, 1024)
    key.shadow.camera.left = -4
    key.shadow.camera.right = 4
    key.shadow.camera.top = 4
    key.shadow.camera.bottom = -4
    key.shadow.normalBias = .035
    key.shadow.bias = -.00015
    key.shadow.radius = 4
    scene.add(key)
    const fill = new THREE.DirectionalLight('#b8dcc6', 4.5)
    fill.position.set(3, 4, -5)
    scene.add(fill)
    const rim = new THREE.DirectionalLight('#ff9b66', 1.8)
    rim.position.set(-4, 2, -3)
    scene.add(rim)
    const payloadLight = new THREE.PointLight('#ff692e', .8, 2.2, 2)
    payloadLight.position.set(1, .7, .3)
    scene.add(payloadLight)

    const world = new THREE.Group()
    world.rotation.y = -.18
    scene.add(world)
    const ground = mesh(new THREE.PlaneGeometry(200, 200), floorMat, scene, [0, -.105, 0])
    ground.rotation.x = -Math.PI / 2
    ground.castShadow = false

    // A machined workcell with a subtle coordinate grid and luminous edge seam.
    const platformShape = new THREE.Shape()
    const width = 4.3, depth = 2.8, corner = .10
    platformShape.moveTo(-width / 2 + corner, -depth / 2)
    platformShape.lineTo(width / 2 - corner, -depth / 2)
    platformShape.quadraticCurveTo(width / 2, -depth / 2, width / 2, -depth / 2 + corner)
    platformShape.lineTo(width / 2, depth / 2 - corner)
    platformShape.quadraticCurveTo(width / 2, depth / 2, width / 2 - corner, depth / 2)
    platformShape.lineTo(-width / 2 + corner, depth / 2)
    platformShape.quadraticCurveTo(-width / 2, depth / 2, -width / 2, depth / 2 - corner)
    platformShape.lineTo(-width / 2, -depth / 2 + corner)
    platformShape.quadraticCurveTo(-width / 2, -depth / 2, -width / 2 + corner, -depth / 2)
    const platform = mesh(new THREE.ExtrudeGeometry(platformShape, { depth: .18, bevelEnabled: true, bevelSegments: 3, steps: 1, bevelSize: .035, bevelThickness: .035 }), platformMat, world, [0, -.045, 0])
    platform.rotation.x = -Math.PI / 2
    const surface = mesh(new THREE.ShapeGeometry(platformShape, 12), tabletopMat, world, [0, .172, 0])
    surface.rotation.x = -Math.PI / 2
    surface.castShadow = false
    for (const [x, z] of [[-1.95, -1.2], [1.95, -1.2], [-1.95, 1.2], [1.95, 1.2]]) {
      cylinder(world, .034, .004, silver, [x, .177, z])
    }
    mesh(new THREE.BoxGeometry(1.08, .012, .016), orangeGlow, world, [.86, .05, 1.419])
    mesh(new THREE.BoxGeometry(.014, .012, .54), orangeGlow, world, [2.168, .05, .84])
    const gridMaterial = new THREE.LineBasicMaterial({ color: '#758c7b', transparent: true, opacity: .14 })
    materials.add(gridMaterial)
    const gridPoints: THREE.Vector3[] = []
    for (let x = -1.8; x <= 1.8; x += .3) gridPoints.push(new THREE.Vector3(x, .176, -1.15), new THREE.Vector3(x, .176, 1.15))
    for (let z = -1.05; z <= 1.06; z += .3) gridPoints.push(new THREE.Vector3(-1.9, .176, z), new THREE.Vector3(1.9, .176, z))
    world.add(new THREE.LineSegments(geometry(new THREE.BufferGeometry().setFromPoints(gridPoints)), gridMaterial))

    const base = new THREE.Group()
    base.position.set(-.95, .18, .25)
    world.add(base)
    cylinder(base, .48, .10, graphite, [0, .05, 0])
    cylinder(base, .43, .045, porcelainEdge, [0, .12, 0])
    cylinder(base, .31, .34, porcelain, [0, .295, 0], .39)
    cylinder(base, .29, .08, graphite, [0, .5, 0])
    cylinder(base, .31, .018, orangeGlow, [0, .548, 0])
    for (const angle of [0, Math.PI / 2, Math.PI, Math.PI * 1.5]) {
      cylinder(base, .035, .012, silver, [Math.cos(angle) * .365, .148, Math.sin(angle) * .365])
    }

    const shoulder = new THREE.Group()
    shoulder.position.set(0, .69, 0)
    base.add(shoulder)
    joint(shoulder, .29)
    const upperEnd = new THREE.Vector3(-.5, 1.32, 0)
    capsule(shoulder, new THREE.Vector3(-.035, .08, 0), upperEnd.clone().multiplyScalar(.94), .255, porcelain)
    capsule(shoulder, new THREE.Vector3(-.115, .34, .233), new THREE.Vector3(-.31, .92, .233), .045, graphite)
    capsule(shoulder, new THREE.Vector3(-.09, .35, -.24), new THREE.Vector3(-.285, .91, -.24), .027, porcelainEdge)

    const elbow = new THREE.Group()
    elbow.position.copy(upperEnd)
    shoulder.add(elbow)
    joint(elbow, .27)
    const forearmEnd = new THREE.Vector3(1.7, -.25, 0)
    capsule(elbow, new THREE.Vector3(.09, -.025, 0), forearmEnd.clone().multiplyScalar(.96), .225, porcelain)
    capsule(elbow, new THREE.Vector3(.39, -.065, .208), new THREE.Vector3(1.37, -.20, .208), .034, porcelainEdge)
    // A dark flexible cable follows the real articulated links.
    const cablePath = new THREE.CatmullRomCurve3([
      new THREE.Vector3(-.02, -.16, -.28), new THREE.Vector3(.25, -.29, -.28),
      new THREE.Vector3(.75, -.3, -.24), new THREE.Vector3(1.4, -.39, -.22), new THREE.Vector3(1.7, -.28, -.21),
    ])
    mesh(new THREE.TubeGeometry(cablePath, 28, .027, 8, false), rubber, elbow)

    const wrist = new THREE.Group()
    wrist.position.copy(forearmEnd)
    elbow.add(wrist)
    joint(wrist, .22)
    const toolEnd = new THREE.Vector3(.48, -.69, 0)
    capsule(wrist, new THREE.Vector3(.03, -.08, 0), toolEnd.clone().multiplyScalar(.85), .168, porcelain)
    const tool = new THREE.Group()
    tool.position.copy(toolEnd)
    tool.rotation.z = .10
    wrist.add(tool)
    cylinder(tool, .155, .14, graphite, [0, .055, 0])
    cylinder(tool, .158, .033, orange, [0, -.035, 0])
    mesh(new THREE.BoxGeometry(.39, .14, .23), graphite, tool, [0, -.12, 0])
    for (const side of [-1, 1]) {
      mesh(new THREE.BoxGeometry(.065, .22, .12), silver, tool, [side * .15, -.29, 0])
      mesh(new THREE.BoxGeometry(.11, .10, .14), rubber, tool, [side * .128, -.415, 0])
      bolt(tool, side * .142, -.13, .124, .019)
    }

    // These are art-directed hypothetical situations, not simulator rollouts.
    const payload = new THREE.Group()
    payload.position.set(.73, .415, .25)
    world.add(payload)
    const block = new THREE.Group()
    payload.add(block)
    // Bevels catch the rim light without needing a loaded model or texture.
    const blockShape = new THREE.Shape()
    blockShape.moveTo(-.2, -.2)
    blockShape.lineTo(.2, -.2)
    blockShape.lineTo(.2, .2)
    blockShape.lineTo(-.2, .2)
    blockShape.closePath()
    mesh(new THREE.ExtrudeGeometry(blockShape, { depth: .4, bevelEnabled: true, bevelSize: .025, bevelThickness: .025, bevelSegments: 3, steps: 1 }), orange, block, [0, 0, -.2])
    mesh(new THREE.BoxGeometry(.19, .006, .25), graphite, block, [0, .226, 0])
    mesh(new THREE.BoxGeometry(.09, .008, .13), orangeGlow, block, [0, .231, 0])

    const roundedLoad = new THREE.Group()
    payload.add(roundedLoad)
    mesh(new THREE.SphereGeometry(.285, 40, 28), orange, roundedLoad)
    const band = mesh(new THREE.TorusGeometry(.283, .016, 10, 48), graphite, roundedLoad)
    band.rotation.x = Math.PI / 2
    const loadCap = cylinder(roundedLoad, .10, .025, silver, [0, 0, .273])
    loadCap.rotation.x = Math.PI / 2
    roundedLoad.rotation.z = .42

    const ghostMaterial = new THREE.LineDashedMaterial({ color: '#b4cbbb', dashSize: .045, gapSize: .035, transparent: true, opacity: .42 })
    materials.add(ghostMaterial)
    const ghostBoxGeometry = geometry(new THREE.BoxGeometry(.45, .45, .45))
    const ghostBox = new THREE.LineSegments(geometry(new THREE.EdgesGeometry(ghostBoxGeometry)), ghostMaterial)
    ghostBox.position.set(.73, .415, .25)
    ghostBox.computeLineDistances()
    world.add(ghostBox)
    const destinationPoints = [new THREE.Vector3(.82, .182, -.53), new THREE.Vector3(1.4, .182, -.53), new THREE.Vector3(1.4, .182, .05), new THREE.Vector3(.82, .182, .05), new THREE.Vector3(.82, .182, -.53)]
    const destination = new THREE.Line(geometry(new THREE.BufferGeometry().setFromPoints(destinationPoints)), ghostMaterial)
    destination.computeLineDistances()
    world.add(destination)

    const barriers = new THREE.Group()
    barriers.position.set(1.43, .18, .38)
    world.add(barriers)
    mesh(new THREE.BoxGeometry(.15, .75, 1.12), graphite, barriers, [0, .375, 0])
    mesh(new THREE.BoxGeometry(.17, .045, 1.14), orange, barriers, [0, .76, 0])
    mesh(new THREE.BoxGeometry(.30, .055, 1.28), porcelainEdge, barriers, [0, .028, 0])
    mesh(new THREE.BoxGeometry(.62, .39, .13), graphite, barriers, [-.38, .195, -.59])
    mesh(new THREE.BoxGeometry(.64, .035, .15), orange, barriers, [-.38, .402, -.59])
    for (const z of [-.4, -.1, .2, .5]) {
      const marking = mesh(new THREE.BoxGeometry(.006, .16, .06), orange, barriers, [-.079, .36, z])
      marking.rotation.x = -.35
    }

    const makePath = (points: THREE.Vector3[], color: string, opacity: number) => {
      const curve = new THREE.CatmullRomCurve3(points)
      const material = new THREE.LineDashedMaterial({ color, dashSize: .035, gapSize: .045, transparent: true, opacity })
      materials.add(material)
      const line = new THREE.Line(geometry(new THREE.BufferGeometry().setFromPoints(curve.getPoints(72))), material)
      line.computeLineDistances()
      world.add(line)
      return { curve, line, material }
    }
    const placementPath = makePath([
      new THREE.Vector3(.73, .46, .25), new THREE.Vector3(.77, .78, .07),
      new THREE.Vector3(1.02, .79, -.15), new THREE.Vector3(1.11, .48, -.24),
    ], '#ff8249', .8)
    const obstaclePath = makePath([
      new THREE.Vector3(.73, .65, .25), new THREE.Vector3(.78, 1.22, .14),
      new THREE.Vector3(1.50, 1.30, -.05), new THREE.Vector3(1.90, .55, -.28),
    ], '#ff8249', .8)
    const dropPath = makePath([
      new THREE.Vector3(.73, .91, .25), new THREE.Vector3(.83, .78, .30),
      new THREE.Vector3(1.03, .45, .46), new THREE.Vector3(1.20, .19, .65),
    ], '#ff8249', .8)
    const dropRing = mesh(new THREE.TorusGeometry(.22, .007, 6, 40), orangeGlow, world, [1.2, .184, .65])
    dropRing.rotation.x = -Math.PI / 2
    dropRing.castShadow = false
    const waypoint = mesh(new THREE.SphereGeometry(.027, 12, 8), orangeGlow, world)
    waypoint.castShadow = false

    const resize = () => {
      if (disposed) return
      const { width: rawWidth, height: rawHeight } = mount.getBoundingClientRect()
      const width = Math.max(1, rawWidth), height = Math.max(1, rawHeight)
      const aspect = width / height
      const halfHeight = Math.max(1.88, 2.40 / aspect)
      camera.left = -halfHeight * aspect
      camera.right = halfHeight * aspect
      camera.top = halfHeight
      camera.bottom = -halfHeight
      camera.updateProjectionMatrix()
      renderer.setSize(width, height, false)
      wake()
    }
    const renderFrame = (timestamp: number) => {
      raf = 0
      if (disposed || !visible || document.hidden) return
      const animate = !reduceMotion && !inputs.current.paused
      if (animate && timestamp - lastFrame < 1000 / 30) {
        raf = window.requestAnimationFrame(renderFrame)
        return
      }
      const delta = Math.min((timestamp - lastFrame) / 1000 || 0, .06)
      lastFrame = timestamp
      if (animate) elapsed += delta
      const activeScenario = inputs.current.scenario
      const transition = (value: number, enabled: boolean) => animate ? THREE.MathUtils.damp(value, enabled ? 1 : 0, 5, delta) : enabled ? 1 : 0
      placementMix = transition(placementMix, activeScenario === 'placement')
      obstacleMix = transition(obstacleMix, activeScenario === 'obstacles')
      gripMix = transition(gripMix, activeScenario === 'grip')
      if (animate) smoothPointer.lerp(pointer, .055)
      else if (reduceMotion) smoothPointer.set(0, 0)
      const scroll = Math.min(1, Math.max(0, inputs.current.progress))
      shoulder.rotation.z = reduceMotion ? 0 : Math.sin(elapsed * .36) * .025
      elbow.rotation.z = reduceMotion ? 0 : Math.sin(elapsed * .36 + .8) * .02
      wrist.rotation.z = reduceMotion ? 0 : Math.sin(elapsed * .36 + 1.8) * .025
      world.rotation.y = -.18 + (reduceMotion ? 0 : scroll * .11 + smoothPointer.x * .06)
      payload.position.set(.73 + placementMix * .38 + gripMix * .035, .415 + gripMix * .21, .25 - placementMix * .49)
      payload.rotation.z = gripMix * .38
      payload.rotation.y = placementMix * .16
      block.scale.setScalar(Math.max(.001, 1 - gripMix))
      block.visible = gripMix < .99
      roundedLoad.scale.setScalar(Math.max(.001, gripMix))
      roundedLoad.visible = gripMix > .01
      ghostMaterial.opacity = .42 * placementMix
      barriers.scale.y = Math.max(.001, obstacleMix)
      barriers.visible = obstacleMix > .01
      placementPath.material.opacity = placementMix * .85
      obstaclePath.material.opacity = obstacleMix * .85
      dropPath.material.opacity = gripMix * .85
      dropRing.scale.setScalar(Math.max(.001, gripMix))
      dropRing.visible = gripMix > .01
      const trajectory = activeScenario === 'placement' ? placementPath.curve : activeScenario === 'obstacles' ? obstaclePath.curve : dropPath.curve
      waypoint.position.copy(trajectory.getPoint(reduceMotion ? .42 : (elapsed * .12) % 1))
      camera.position.y = 3.35 + smoothPointer.y * .15
      camera.lookAt(target)
      renderer.render(scene, camera)
      if (animate) raf = window.requestAnimationFrame(renderFrame)
    }
    function wake() {
      if (!disposed && visible && !document.hidden && !raf) {
        lastFrame = performance.now() - 34
        raf = window.requestAnimationFrame(renderFrame)
      }
    }
    const onMove = (event: PointerEvent) => {
      if (event.pointerType === 'touch') return
      const bounds = mount.getBoundingClientRect()
      pointer.set((event.clientX - bounds.left) / bounds.width * 2 - 1, (event.clientY - bounds.top) / bounds.height * 2 - 1)
      wake()
    }
    const onLeave = () => pointer.set(0, 0)
    const onMotionChange = (event: MediaQueryListEvent) => { reduceMotion = event.matches; wake() }
    const onVisibility = () => {
      if (document.hidden && raf) { cancelAnimationFrame(raf); raf = 0 }
      else wake()
    }
    const onContextLost = (event: Event) => {
      event.preventDefault()
      if (!disposed) { setFailed(true); cancelAnimationFrame(raf); raf = 0; visible = false }
    }
    const observerVisibility = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting
      if (!visible && raf) { cancelAnimationFrame(raf); raf = 0 }
      else wake()
    }, { rootMargin: '100px' })
    const resizeObserver = new ResizeObserver(resize)
    observerVisibility.observe(mount)
    resizeObserver.observe(mount)
    mount.addEventListener('pointermove', onMove, { passive: true })
    mount.addEventListener('pointerleave', onLeave)
    renderer.domElement.addEventListener('webglcontextlost', onContextLost)
    mediaQuery.addEventListener('change', onMotionChange)
    document.addEventListener('visibilitychange', onVisibility)
    wakeRef.current = wake
    resize()

    return () => {
      disposed = true
      wakeRef.current = null
      cancelAnimationFrame(raf)
      observerVisibility.disconnect()
      resizeObserver.disconnect()
      mount.removeEventListener('pointermove', onMove)
      mount.removeEventListener('pointerleave', onLeave)
      renderer.domElement.removeEventListener('webglcontextlost', onContextLost)
      mediaQuery.removeEventListener('change', onMotionChange)
      document.removeEventListener('visibilitychange', onVisibility)
      geometries.forEach(value => value.dispose())
      materials.forEach(value => value.dispose())
      scene.environment = null
      environmentMap.dispose()
      key.shadow.map?.dispose()
      renderer.renderLists.dispose()
      renderer.dispose()
      renderer.forceContextLoss()
      renderer.domElement.remove()
    }
  }, [])

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }} aria-hidden="true">
      <div ref={mountRef} style={{ width: '100%', height: '100%', visibility: failed ? 'hidden' : 'visible' }} />
      {failed && <div style={{ position: 'absolute', inset: 0 }}><ForgeSceneFallback scenario={scenario} /></div>}
    </div>
  )
}
