export interface VpcService {
  fetch(request: Request): Promise<Response>;
}

export interface Env {
  ORIGIN: VpcService;
  BRIDGE_WEBSOCKETS?: string;
}

const FORWARDED_HEADERS = new Set([
  "forwarded",
  "x-real-ip",
  "x-forwarded-for",
  "x-forwarded-host",
  "x-forwarded-port",
  "x-forwarded-prefix",
  "x-forwarded-proto",
]);

const HOP_BY_HOP_HEADERS = [
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "proxy-connection",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
];

function proxyHeaders(request: Request, publicUrl: URL): Headers {
  const headers = new Headers(request.headers);
  for (const name of [...headers.keys()]) {
    const lower = name.toLowerCase();
    if (FORWARDED_HEADERS.has(lower) || lower.startsWith("x-forwarded-")) {
      headers.delete(name);
    }
  }
  for (const name of HOP_BY_HOP_HEADERS) headers.delete(name);

  headers.set("host", publicUrl.host);
  headers.set("x-forwarded-host", publicUrl.host);
  headers.set("x-forwarded-proto", publicUrl.protocol.slice(0, -1));
  headers.set("x-forwarded-port", publicUrl.port || (publicUrl.protocol === "https:" ? "443" : "80"));
  if (request.headers.get("upgrade")?.toLowerCase() === "websocket") {
    headers.set("connection", "Upgrade");
    headers.set("upgrade", "websocket");
  }
  return headers;
}

function upstreamRequest(request: Request, publicUrl: URL): Request {
  const target = new URL(publicUrl.pathname + publicUrl.search, `http://${publicUrl.host}`);
  const init: RequestInit & { duplex?: "half" } = {
    method: request.method,
    headers: proxyHeaders(request, publicUrl),
    redirect: "manual",
  };
  if (request.body && request.method !== "GET" && request.method !== "HEAD") {
    init.body = request.body;
    init.duplex = "half";
  }
  return new Request(target, init);
}

function closeCode(code: number): number {
  return code === 1000 || (code >= 3000 && code <= 4999) ? code : 1011;
}

function closeSocket(socket: WebSocket, code: number): void {
  if (socket.readyState >= 2) return;
  try {
    socket.close(code);
  } catch {
    try {
      socket.close(1011);
    } catch {
      // The peer may already have completed its close handshake.
    }
  }
}

export function bridgeWebSockets(client: WebSocket, origin: WebSocket): void {
  let closed = false;
  const closeBoth = (code = 1011): void => {
    if (closed) return;
    closed = true;
    closeSocket(client, code);
    closeSocket(origin, code);
  };

  const forward = (from: WebSocket, to: WebSocket): void => {
    from.addEventListener("message", (event: MessageEvent) => {
      if (to.readyState !== 1) {
        closeBoth();
        return;
      }
      try {
        to.send(event.data as string | ArrayBuffer | ArrayBufferView);
      } catch {
        closeBoth();
      }
    });
    from.addEventListener("close", (event: CloseEvent) => {
      const code = closeCode(event.code);
      if (to.readyState < 2) closeSocket(to, code);
    });
    from.addEventListener("error", () => closeBoth());
  };

  forward(client, origin);
  forward(origin, client);
}

async function handleRequest(request: Request, env: Env): Promise<Response> {
  const publicUrl = new URL(request.url);
  const isWebSocket = request.headers.get("upgrade")?.toLowerCase() === "websocket";
  const proxy = upstreamRequest(request, publicUrl);

  let response: Response;
  try {
    response = await env.ORIGIN.fetch(proxy);
  } catch {
    return new Response("Staging origin unavailable", {
      status: 502,
      headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" },
    });
  }

  if (
    isWebSocket &&
    env.BRIDGE_WEBSOCKETS === "true" &&
    response.status === 101 &&
    response.webSocket
  ) {
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair) as [WebSocket, WebSocket];
    server.accept({ allowHalfOpen: true });
    response.webSocket.accept({ allowHalfOpen: true });
    bridgeWebSockets(server, response.webSocket);
    return new Response(null, { status: 101, webSocket: client });
  }

  // Returning the VPC response itself preserves redirects, repeated Set-Cookie headers and
  // streaming bodies without buffering or reconstructing them.
  return response;
}

export default {
  fetch(request: Request, env: Env): Promise<Response> {
    return handleRequest(request, env);
  },
} satisfies ExportedHandler<Env>;
