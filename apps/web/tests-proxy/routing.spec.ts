import { expect, test } from "@playwright/test";
import { NextRequest } from "next/server";
import { proxy, upstreamFor } from "../src/proxy";

test("routes readiness and simulator requests to the intended paths", () => {
  const env = { PRAMANA_CORE_URL: "https://core.example", PRAMANA_SIM_URL: "https://sim.example" };
  expect(upstreamFor("/ready", "", env)?.href).toBe("https://core.example/ready");
  expect(upstreamFor("/api/sim/sim/v1/view", "?x=1", env)?.href).toBe("https://sim.example/sim/v1/view?x=1");
});

test("keeps the app bearer while authenticating the private service", async () => {
  const originalFetch = globalThis.fetch;
  const originalCore = process.env.PRAMANA_CORE_URL;
  const originalAuth = process.env.PRAMANA_CLOUD_RUN_AUTH;
  const payload = Buffer.from(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 })).toString("base64url");
  const token = `header.${payload}.signature`;
  let audience = "";
  globalThis.fetch = async (input, init) => {
    audience = new URL(String(input)).searchParams.get("audience") ?? "";
    expect(new Headers(init?.headers).get("Metadata-Flavor")).toBe("Google");
    return new Response(token);
  };
  process.env.PRAMANA_CORE_URL = "https://core.example";
  process.env.PRAMANA_CLOUD_RUN_AUTH = "true";
  try {
    const response = await proxy(new NextRequest("https://web.example/api/core/v1/example", {
      headers: { Authorization: "Bearer participant-token", "X-Serverless-Authorization": "untrusted" },
    }));
    expect(audience).toBe("https://core.example");
    expect(response.headers.get("x-middleware-request-authorization")).toBe("Bearer participant-token");
    expect(response.headers.get("x-middleware-request-x-serverless-authorization")).toBe(`Bearer ${token}`);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalCore === undefined) delete process.env.PRAMANA_CORE_URL;
    else process.env.PRAMANA_CORE_URL = originalCore;
    if (originalAuth === undefined) delete process.env.PRAMANA_CLOUD_RUN_AUTH;
    else process.env.PRAMANA_CLOUD_RUN_AUTH = originalAuth;
  }
});
