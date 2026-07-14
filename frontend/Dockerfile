ARG NODE_IMAGE=public.ecr.aws/docker/library/node:22-alpine
ARG NGINX_IMAGE=public.ecr.aws/docker/library/nginx:1.29-alpine
FROM ${NODE_IMAGE} AS build
WORKDIR /app
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM ${NGINX_IMAGE}
RUN apk add --no-cache apache2-utils
COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY frontend/40-create-auth-file.sh /docker-entrypoint.d/40-create-auth-file.sh
EXPOSE 80
