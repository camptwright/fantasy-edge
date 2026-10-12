# CONSTRAINT #10: output:'standalone' in next.config.js is what makes the
# final `node server.js` CMD below work without node_modules in this layer.
FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
# --legacy-peer-deps: swr/next/react version ranges across a security-patch
# bump have occasionally disagreed just enough for a strict peer-dep
# resolution to fail even though the versions are actually compatible.
RUN npm ci --legacy-peer-deps

FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN node scripts/release-provenance.cjs source > release-source.json \
 && npm run build

FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN useradd --create-home --uid 1001 nextjs
COPY --from=builder /app/public* ./public
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static
COPY --from=builder /app/release-source.json ./release-source.json
COPY --from=builder /app/scripts/release-provenance.cjs ./release-provenance.cjs
RUN node release-provenance.cjs seal
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
