# Дашборд Windcast. Контекст сборки — корень репозитория: нужны workspaces.
FROM node:22-alpine AS build
WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json turbo.json tsconfig.json ./
COPY apps/web/package.json ./apps/web/
COPY packages ./packages
RUN npm ci --no-audit --no-fund

COPY apps ./apps
# rewrites() в next.config вычисляется во время сборки, поэтому адрес API
# нужен уже здесь: внутри сети compose backend доступен по имени сервиса.
ENV RENTBOX_API_URL=http://backend:8000/api
RUN npm run build --workspace web

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/packages ./packages
COPY --from=build /app/apps/web ./apps/web

RUN addgroup -g 10002 app && adduser -u 10002 -G app -D app && chown -R app:app /app
USER app

EXPOSE 3000
CMD ["npm", "run", "start", "--workspace", "web"]
