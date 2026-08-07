import * as React from "react"
import { expect, test } from "bun:test"

import { CardMoreMenu } from "../components/ui/card-more-menu"

test("stops clicks from the portalled menu content", () => {
  const menu = CardMoreMenu({ label: "More", children: null })
  const [, content] = React.Children.toArray(menu.props.children) as [
    React.ReactElement,
    React.ReactElement<{
      onClick?: (event: { stopPropagation: () => void }) => void
    }>,
  ]
  let stopped = false

  content.props.onClick?.({
    stopPropagation: () => {
      stopped = true
    },
  })

  expect(stopped).toBe(true)
})
