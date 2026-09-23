import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"

const css = readFileSync(
  new URL("../apps/web/app/appearance.css", import.meta.url),
  "utf8"
)
function palette(selector) {
  const start = css.indexOf(`${selector} {`)
  assert.ok(start >= 0, selector)
  const block = css.slice(start, css.indexOf("}", start))
  return Object.fromEntries(
    [...block.matchAll(/(--[\w-]+):\s*(#[\da-f]{6});/gi)].map((m) => [
      m[1],
      m[2],
    ])
  )
}
function luminance(hex) {
  const linear = [1, 3, 5]
    .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722
}
function contrast(a, b) {
  const x = luminance(a),
    y = luminance(b)
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
}
for (const [selector, threshold] of [
  [":root.dark", 4.5],
  [':root[data-vision="high"]', 7],
  [':root.dark[data-vision="high"]', 7],
]) {
  test(`${selector}: text palette remains readable across panels and semantic states`, () => {
    const p = palette(selector)
    for (const [foreground, background] of [
      ["text", "canvas"],
      ["text", "panel"],
      ["muted", "panel"],
      ["muted", "soft"],
      ["text", "accent-soft"],
      ["on-accent", "accent"],
      ["info-text", "info-soft"],
      ["warning-text", "warning-soft"],
    ]) {
      const ratio = contrast(
        p[`--wc-theme-${foreground}`],
        p[`--wc-theme-${background}`]
      )
      assert.ok(
        ratio >= threshold,
        `${foreground}/${background}: ${ratio.toFixed(2)} < ${threshold}`
      )
    }
    for (const key of ["forecast", "actual"]) {
      const ratio = contrast(p[`--wc-chart-${key}`], p["--wc-theme-panel"])
      assert.ok(ratio >= 3, `Chart ${key}: ${ratio.toFixed(2)} < 3`)
    }
    assert.ok(
      contrast(p["--wc-control-text"], p["--wc-control-bg"]) >= threshold
    )
    assert.ok(contrast(p["--wc-control-ring"], p["--wc-control-bg"]) >= 3)
  })
}
