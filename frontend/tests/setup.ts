/* Shared DOM test setup: registers happy-dom globals for every test file. */
import { GlobalRegistrator } from "@happy-dom/global-registrator"
import { createRequire } from "node:module"

GlobalRegistrator.register()

// Must load Testing Library AFTER the happy-dom globals exist, otherwise its
// `screen` binds to an undefined document.
const { configure } = createRequire(import.meta.url)(
  "@testing-library/react"
) as typeof import("@testing-library/react")
// Parallel workers share CPU; the default 1s waitFor budget is too tight and
// makes otherwise-correct tests flaky.
configure({ asyncUtilTimeout: 5000 })
