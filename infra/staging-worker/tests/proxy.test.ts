import { afterEach, describe, expect, it, vi } from "vitest";
import worker, { bridgeWebSockets, type Env } from "../src/index";

type FetchRequest = Request;

function binding(fetch: (request: FetchRequest) => Promise<Response>): Env {
  return { ORIGIN: { fetch } };
}

function fakeSocket(): FakeSocket {
  return new FakeSocket();
}

class FakeSocket {
  readyState = 1;
  readonly sent: (string | ArrayBuffer | ArrayBufferView)[] = [];
  readonly closed: number[] = [];
  private readonly listeners = new Map<string, ((event: never) => void)[]>();

  addEventListener(type: string, listener: (event: never) => void): void {
    const current = this.listeners.get(type) ?? [];
    current.push(listener);
    this.listeners.set(type, current);
  }

  send(data: string | ArrayBuffer | ArrayBufferView): void {
    this.sent.push(data);
  }

  close(code = 1000): void {
    this.closed.push(code);
    this.readyState = 3;
  }

  emit(type: string, event: object = {}): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event as never);
  }
}

describe("staging Worker HTTP proxy", () => {
  afterEach(() => vi.restoreAllMocks());

  it.each(["GET", "POST", "PATCH", "DELETE", "OPTIONS", "HEAD"]) (
    "preserves the %s request method, route and query",
    async (method) => {
      let received: Request | undefined;
      const response = new Response(null, { status: 204 });
      const request = new Request(
        `https://pramana-staging.account.workers.dev/api/core/items?limit=3`,
        { method },
      );
      const proxied = await worker.fetch(
        request,
        binding(async (upstream) => {
          received = upstream;
          return response;
        }),
      );

      expect(proxied).toBe(response);
      expect(received?.method).toBe(method);
      expect(received?.url).toBe(
        "http://pramana-staging.account.workers.dev/api/core/items?limit=3",
      );
    },
  );

  it("preserves request headers and replaces client-supplied forwarded headers", async () => {
    let received: Request | undefined;
    const response = new Response("ok");
    const request = new Request("https://pramana-staging.account.workers.dev/anything", {
      headers: {
        "x-custom-header": "kept",
        "x-forwarded-host": "attacker.example",
        "x-forwarded-proto": "http",
        "x-forwarded-for": "192.0.2.1",
        forwarded: "for=192.0.2.1;proto=http;host=attacker.example",
      },
    });

    await worker.fetch(
      request,
      binding(async (upstream) => {
        received = upstream;
        return response;
      }),
    );

    expect(received?.headers.get("x-custom-header")).toBe("kept");
    expect(received?.headers.get("x-forwarded-host")).toBe("pramana-staging.account.workers.dev");
    expect(received?.headers.get("x-forwarded-proto")).toBe("https");
    expect(received?.headers.get("x-forwarded-for")).toBeNull();
    expect(received?.headers.get("forwarded")).toBeNull();
  });

  it("forwards streaming bodies and returns response headers and body untouched", async () => {
    const headers = new Headers({
      "content-type": "text/event-stream",
      "cache-control": "no-cache, no-transform",
      location: "/next",
    });
    headers.append("set-cookie", "first=one; Path=/; HttpOnly");
    headers.append("set-cookie", "second=two; Path=/; Secure");
    const chunks = ["data: one\n\n", "data: two\n\n"];
    const upstream = new Response(
      new ReadableStream<Uint8Array>({
        start(controller) {
          for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
          controller.close();
        },
      }),
      { status: 206, headers },
    );
    let receivedBody = "";

    const returned = await worker.fetch(
      new Request("https://pramana-staging.account.workers.dev/api/core/stream", {
        method: "POST",
        body: "request-body",
      }),
      binding(async (request) => {
        receivedBody = await request.text();
        return upstream;
      }),
    );

    expect(receivedBody).toBe("request-body");
    expect(returned).toBe(upstream);
    expect(returned.status).toBe(206);
    expect(returned.headers.get("cache-control")).toBe("no-cache, no-transform");
    expect(returned.headers.get("location")).toBe("/next");
    expect(returned.headers.getSetCookie()).toEqual([
      "first=one; Path=/; HttpOnly",
      "second=two; Path=/; Secure",
    ]);
    expect(await returned.text()).toBe(chunks.join(""));
  });

  it("does not follow an upstream redirect", async () => {
    let received: Request | undefined;
    const redirect = new Response(null, { status: 302, headers: { location: "/signin" } });

    const returned = await worker.fetch(
      new Request("https://pramana-staging.account.workers.dev/private"),
      binding(async (request) => {
        received = request;
        return redirect;
      }),
    );

    expect(received?.redirect).toBe("manual");
    expect(returned).toBe(redirect);
    expect(returned.status).toBe(302);
    expect(returned.headers.get("location")).toBe("/signin");
  });

  it("returns a generic 502 when the VPC origin is unavailable", async () => {
    const returned = await worker.fetch(
      new Request("https://pramana-staging.account.workers.dev/"),
      binding(async () => {
        throw new Error("upstream detail");
      }),
    );

    expect(returned.status).toBe(502);
    expect(await returned.text()).toBe("Staging origin unavailable");
  });
});

describe("WebSocket proxy", () => {
  it("passes the VPC 101 response through without consuming it", async () => {
    let received: Request | undefined;
    const upstreamSocket = fakeSocket();
    const upgrade = { status: 101, webSocket: upstreamSocket } as unknown as Response;
    const request = new Request(
      "https://pramana-staging.account.workers.dev/api/core/v1/investigations/id/questions/q/media",
      {
        headers: {
          connection: "keep-alive",
          upgrade: "websocket",
          "sec-websocket-key": "client-key",
          "sec-websocket-version": "13",
          "x-forwarded-host": "spoofed.example",
        },
      },
    );

    const returned = await worker.fetch(
      request,
      binding(async (upstream) => {
        received = upstream;
        return upgrade;
      }),
    );

    expect(received?.headers.get("upgrade")).toBe("websocket");
    expect(received?.headers.get("connection")).toBe("Upgrade");
    expect(received?.headers.get("sec-websocket-key")).toBe("client-key");
    expect(received?.headers.get("x-forwarded-host")).toBe("pramana-staging.account.workers.dev");
    expect(returned).toBe(upgrade);
  });

  it("bridges text and binary frames in both directions", () => {
    const client = fakeSocket();
    const origin = fakeSocket();

    bridgeWebSockets(client as unknown as WebSocket, origin as unknown as WebSocket);
    client.emit("message", { data: "hello" });
    client.emit("message", { data: new Uint8Array([1, 2, 3]) });
    origin.emit("message", { data: "world" });
    origin.emit("message", { data: new Uint8Array([4, 5, 6]) });

    expect(origin.sent[0]).toBe("hello");
    expect(Array.from(origin.sent[1] as Uint8Array)).toEqual([1, 2, 3]);
    expect(client.sent[0]).toBe("world");
    expect(Array.from(client.sent[1] as Uint8Array)).toEqual([4, 5, 6]);
  });

  it("closes both sockets when either side errors or a frame cannot be forwarded", () => {
    const client = fakeSocket();
    const origin = fakeSocket();

    bridgeWebSockets(client as unknown as WebSocket, origin as unknown as WebSocket);
    client.emit("error");

    expect(client.closed).toEqual([1011]);
    expect(origin.closed).toEqual([1011]);
  });

  it("closes the opposite side when one side closes", () => {
    const client = fakeSocket();
    const origin = fakeSocket();

    bridgeWebSockets(client as unknown as WebSocket, origin as unknown as WebSocket);
    client.emit("close", { code: 1000 });

    expect(origin.closed).toEqual([1000]);
  });
});
