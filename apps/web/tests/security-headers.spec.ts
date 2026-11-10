import { expect, test } from "@playwright/test";

const securityHeaders = {
  "strict-transport-security": "max-age=31536000; includeSubDomains",
  "x-content-type-options": "nosniff",
  "x-frame-options": "DENY",
  "referrer-policy": "no-referrer",
  "permissions-policy": "camera=(), geolocation=(), microphone=(self)",
};

test("serves security headers on pages and missing routes", async ({ request }) => {
  for (const [path, expectedStatus] of [
    ["/", 200],
    ["/login", 200],
    ["/__security_headers_missing_route__", 404],
  ] as const) {
    const response = await request.get(path);
    expect(response.status(), path).toBe(expectedStatus);
    const headers = response.headers();
    for (const [name, value] of Object.entries(securityHeaders)) {
      expect(headers[name], `${path} ${name}`).toBe(value);
    }
    expect(headers["content-security-policy"], `${path} CSP`).toContain("default-src 'self'");
    expect(headers["content-security-policy"], `${path} CSP`).toContain("frame-ancestors 'none'");
    expect(headers["content-security-policy"], `${path} CSP`).toContain("object-src 'none'");
    // Only the development server may evaluate strings; the shipped policy never does.
    expect(headers["content-security-policy"], `${path} CSP`).not.toContain("unsafe-eval");
  }
});
