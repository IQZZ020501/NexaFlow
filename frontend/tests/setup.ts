/* Shared DOM test setup: registers happy-dom globals for every test file. */
import { GlobalRegistrator } from "@happy-dom/global-registrator"

GlobalRegistrator.register()

// Must load Testing Library AFTER the happy-dom globals exist, otherwise its
// `screen` binds to an undefined document.
const { configure } = await import("@testing-library/react")
// Parallel workers share CPU; the default 1s waitFor budget is too tight and
// makes otherwise-correct tests flaky.
configure({ asyncUtilTimeout: 5000 })
