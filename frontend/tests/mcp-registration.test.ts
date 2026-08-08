import { describe, expect, test } from "bun:test"

import {
  buildMcpServerCreatePayload,
  type McpForm,
} from "@/components/tools/mcp-tools-page"

function form(overrides: Partial<McpForm> = {}): McpForm {
  return {
    name: "Release tools",
    transport: "streamable_http",
    url: "https://mcp.example.com/mcp",
    bearerToken: "secret",
    stdioConfig: "",
    ...overrides,
  }
}

describe("MCP registration payloads", () => {
  test("keeps remote credentials only for HTTP transports", () => {
    expect(buildMcpServerCreatePayload(form())).toEqual({
      name: "Release tools",
      transport: "streamable_http",
      url: "https://mcp.example.com/mcp",
      bearer_token: "secret",
    })
    expect(
      buildMcpServerCreatePayload(
        form({ transport: "sse", url: "https://mcp.example.com/sse/" })
      )
    ).toEqual({
      name: "Release tools",
      transport: "sse",
      url: "https://mcp.example.com/sse/",
      bearer_token: "secret",
    })
  })

  test("stdio sends the configuration entered in the form", () => {
    expect(
      buildMcpServerCreatePayload(
        form({
          transport: "stdio",
          url: "https://ignored.example.com",
          bearerToken: "ignored-secret",
          stdioConfig: JSON.stringify({
            command: "/usr/local/bin/node",
            args: ["server.js", "--stdio"],
            cwd: "/srv/mcp",
            env: { API_KEY: "secret=value", EMPTY: "" },
            transport: "stdio",
          }),
        })
      )
    ).toEqual({
      name: "Release tools",
      transport: "stdio",
      stdio_config: {
        command: "/usr/local/bin/node",
        args: ["server.js", "--stdio"],
        cwd: "/srv/mcp",
        env: { API_KEY: "secret=value", EMPTY: "" },
      },
    })
  })

  test("rejects incomplete transport-specific fields", () => {
    expect(buildMcpServerCreatePayload(form({ url: "" }))).toBeNull()
    expect(
      buildMcpServerCreatePayload(form({ transport: "stdio", stdioConfig: "" }))
    ).toBeNull()
    expect(
      buildMcpServerCreatePayload(
        form({
          transport: "stdio",
          stdioConfig: "not-json",
        })
      )
    ).toBeNull()
    expect(
      buildMcpServerCreatePayload(
        form({
          transport: "stdio",
          stdioConfig: JSON.stringify({
            command: "/usr/bin/python3",
            env: { INVALID: 1 },
          }),
        })
      )
    ).toBeNull()
  })
})
