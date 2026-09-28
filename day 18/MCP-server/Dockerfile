# --- Stage 1: build ---
FROM node:22-alpine AS build
WORKDIR /app

# Копируем манифесты первыми для кэширования слоёв npm ci
COPY package.json package-lock.json ./
COPY web/package.json web/package.json
RUN npm ci --no-audit --no-fund

# Исходники и сборка backend + web
COPY . .
RUN npm run build

# --- Stage 2: runtime ---
FROM node:22-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app

COPY --from=build /app/package.json /app/package-lock.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY --from=build /app/web/dist ./web/dist
COPY --from=build /app/config ./config
RUN mkdir -p /app/data/logs

# По умолчанию слушаем ТОЛЬКО 127.0.0.1 (см. docker-compose: проброс тоже на 127.0.0.1)
ENV MCP_HOST=127.0.0.1 \
    MCP_PORT=3000

EXPOSE 3000
CMD ["node", "dist/src/server/index.js"]