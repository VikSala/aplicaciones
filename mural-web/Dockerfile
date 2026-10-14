# syntax=docker/dockerfile:1.7

FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM deps AS development
ENV NODE_ENV=development
COPY . .
EXPOSE 5173 3001
CMD ["npm", "run", "dev:web"]

FROM deps AS builder
ENV NODE_ENV=production
COPY index.html vite.config.ts postcss.config.js tailwind.config.js ./
COPY public ./public
COPY src ./src
RUN npm run build

FROM node:24-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    API_PORT=3001 \
    STATIC_DIR=/app/dist \
    USAGE_DATA_FILE=/app/data/usage.json

COPY package.json ./package.json
COPY server ./server
COPY src/core ./src/core
COPY src/learning ./src/learning
COPY --from=builder /app/dist ./dist

RUN mkdir -p /app/data && chown -R node:node /app
USER node

EXPOSE 3001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3001/api/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

CMD ["node", "server/index.ts"]
