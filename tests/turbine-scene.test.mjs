import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import {
  resolveHour,
  resolveSceneMode,
  illustrativeRotorSpeed,
} from "../apps/web/lib/turbine-scene.ts"

test("navigation selects a meaningful scene and agent execution owns the scene until completion", () => {
  assert.equal(resolveSceneMode("overview", null, false, 0), "flow")
  assert.equal(resolveSceneMode("forecast", null, false, 0), "flow")
  assert.equal(resolveSceneMode("agent", null, false, 0), "cutaway")
  assert.equal(resolveSceneMode("sources", null, false, 0), "sensors")
  assert.equal(resolveSceneMode("history", null, false, 0), "history")
  assert.deepEqual(
    Array.from({ length: 6 }, (_, step) =>
      resolveSceneMode("agent", "history", true, step)
    ),
    ["sensors", "sensors", "cutaway", "flow", "icing", "flow"]
  )
  assert.equal(resolveSceneMode("agent", "icing", false, 5), "icing")
})

test("a selected hour stays valid when switching from 48 to 24 hours", () => {
  assert.equal(resolveHour(47, 48), 47)
  assert.equal(resolveHour(47, 24), 23)
  assert.equal(resolveHour(-1, 24), 0)
  assert.equal(resolveHour(12, 24), 12)
})

test("inspection and history freeze the rotor without inventing production losses", () => {
  assert.equal(illustrativeRotorSpeed(12, "icing"), 0)
  assert.equal(illustrativeRotorSpeed(12, "history"), 0)
  assert.equal(illustrativeRotorSpeed(0, "flow"), 0)
  assert.ok(
    illustrativeRotorSpeed(12, "flow") > illustrativeRotorSpeed(6, "flow")
  )
  assert.ok(
    illustrativeRotorSpeed(12, "cutaway") < illustrativeRotorSpeed(12, "flow")
  )
})

test("the Blender asset contains independent blades and the drivetrain used by the cutaway", () => {
  const bytes = readFileSync(
    new URL("../apps/web/public/models/windcast-turbine.glb", import.meta.url)
  )
  assert.equal(bytes.readUInt32LE(0), 0x46546c67)
  assert.equal(bytes.readUInt32LE(8), bytes.length)
  const gltf = JSON.parse(
    bytes.subarray(20, 20 + bytes.readUInt32LE(12)).toString()
  )
  const rotor = gltf.nodes.find((n) => n.name === "Rotor")
  assert.ok(rotor)
  assert.deepEqual(
    rotor.children
      .map((i) => gltf.nodes[i].name)
      .filter((n) => n.startsWith("Blade_")),
    ["Blade_01", "Blade_02", "Blade_03"]
  )
  for (const name of [
    "Internal_MainShaft",
    "Internal_Gearbox",
    "Internal_Generator",
  ])
    assert.ok(
      gltf.nodes.some((n) => n.name === name),
      name
    )
  assert.ok(gltf.buffers.every((b) => !b.uri))
  assert.ok((gltf.images ?? []).every((i) => !i.uri))
})
