import { expect, test } from "bun:test"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"

import { IconButton } from "../src/components/ui/icon-button"

test("icon button forwards dropdown trigger attributes", () => {
  const markup = renderToStaticMarkup(
    createElement(IconButton, {
      label: "More",
      "aria-haspopup": "menu",
      "aria-expanded": false,
      children: createElement("span"),
    })
  )

  expect(markup).toContain('aria-haspopup="menu"')
  expect(markup).toContain('aria-expanded="false"')
})
