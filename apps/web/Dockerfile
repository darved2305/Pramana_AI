# The web console as a Next.js standalone server (ADR 0025). Build from apps/web:
#   docker build -t pramana-web apps/web
# Upstreams are runtime settings, read per request by src/proxy.ts:
#   docker run -e PRAMANA_CORE_URL=http://core:8080 -e PRAMANA_SIM_URL=http://sim:8080 -p 3000:3000 pramana-web

FROM node:22-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-bookworm-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
RUN useradd --system --uid 10001 nextjs
COPY --from=build --chown=nextjs /app/.next/standalone ./
COPY --from=build --chown=nextjs /app/.next/static ./.next/static
COPY --from=build --chown=nextjs /app/public ./public
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
