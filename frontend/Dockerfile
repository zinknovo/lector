FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM nginx:1.29-alpine
RUN apk add --no-cache apache2-utils
COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY frontend/40-create-auth-file.sh /docker-entrypoint.d/40-create-auth-file.sh
EXPOSE 80
