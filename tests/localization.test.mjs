import test from "node:test"
import assert from "node:assert/strict"
import {
  translations,
  translate,
  isLocale,
  localeTags,
} from "../apps/web/lib/translations.ts"
import {
  AGENT_STEPS,
  TURBINES,
  formatDate,
  formatTimestamp,
  number,
  forecastCsv,
  generateForecast,
} from "../apps/web/lib/forecast-data.ts"
import fs from "node:fs"
import ts from "typescript"

const variables = (message) =>
  [...message.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()
test("English and Kazakh messages preserve all interpolation parameters", () => {
  for (const [source, localized] of Object.entries(translations)) {
    for (const locale of ["en", "kk"]) {
      assert.ok(localized[locale]?.trim(), `${locale}: ${source}`)
      assert.deepEqual(
        variables(localized[locale]),
        variables(source),
        `${locale}: ${source}`
      )
    }
  }
  assert.equal(
    translate("en", "Шаг {v0}: {v1}", { v0: 3, v1: "Run model" }),
    "Step 3: Run model"
  )
  assert.equal(
    translate("kk", "Ожидается в {v0}", { v0: "12:00" }),
    "Күтілетін уақыт: 12:00"
  )
  assert.equal(
    translate("ru", "Шаг {v0}: {v1}", { v0: 0, v1: "Тест" }),
    "Шаг 0: Тест"
  )
  assert.equal(translate("en", "ECMWF IFS"), "ECMWF IFS")
})
test("UI translation keys and scene metadata have both requested languages", () => {
  for (const key of [
    ...AGENT_STEPS.flatMap((s) => [s.title, s.detail]),
    ...TURBINES.flatMap((t) => [t.name, t.location]),
  ])
    assert.ok(translations[key], key)
  const componentFiles = [
    "wind-dashboard.tsx",
    "turbine-hero.tsx",
    "turbine-stage.tsx",
    "forecast-focus.tsx",
    "locale-provider.tsx",
  ]
  const files = componentFiles
    .map((f) => `apps/web/components/${f}`)
    .concat([
      "apps/web/lib/turbine-scene.ts",
      "apps/web/lib/forecast-insights.ts",
    ])
  for (const file of files) {
    const source = fs.readFileSync(file, "utf8")
    const ast = ts.createSourceFile(
      file,
      source,
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TSX
    )
    function visit(node) {
      if (
        ts.isStringLiteral(node) &&
        /[А-Яа-яЁё]/.test(node.text) &&
        !["Русский", "Қазақша"].includes(node.text)
      ) {
        assert.ok(
          translations[node.text],
          `Missing translation: ${file}: ${node.text}`
        )
      }
      if (
        ts.isJsxText(node) &&
        !["Русский", "Қазақша"].includes(node.text.trim())
      )
        assert.ok(
          !/[А-Яа-яЁё]/.test(node.text),
          `Untranslated JSX in ${file}: ${node.text.trim()}`
        )
      ts.forEachChild(node, visit)
    }
    visit(ast)
  }
})
test("locale validation and formatting preserve Kazakhstan time and decimal conventions", () => {
  for (const locale of ["ru", "en", "kk"]) assert.equal(isLocale(locale), true)
  for (const invalid of [null, undefined, "", "fr", "en-US", "__proto__"])
    assert.equal(isLocale(invalid), false)
  assert.equal(formatDate("2026-02-01", true, "en-GB"), "01 February")
  assert.equal(formatDate("2026-02-01", true, "kk-KZ"), "01 ақпан")
  assert.equal(
    formatDate("2026-02-28T19:00:00.000Z", false, "kk-KZ"),
    "01 нау."
  )
  assert.equal(
    formatTimestamp("2026-01-31T18:00:00.000Z", "kk-KZ"),
    "31 қаң., 23:00"
  )
  for (let month = 1; month <= 12; month++)
    assert.ok(
      !formatDate(
        `2026-${String(month).padStart(2, "0")}-01`,
        true,
        "kk-KZ"
      ).includes("M0")
    )
  assert.equal(number(56.12, 1, "en-GB"), "56.1")
  assert.equal(number(56.12, 1, "kk-KZ"), "56,1")
  const points = generateForecast("2026-02-28", 48, "all")
  const csv = forecastCsv(points, "2026-02-28", "all")
  for (const locale of Object.values(localeTags)) {
    formatDate(points.at(-1).date, true, locale)
    number(points[0].forecast, 2, locale)
    assert.equal(forecastCsv(points, "2026-02-28", "all"), csv)
  }
})
