# syntax=docker/dockerfile:1

# Web UI image: nginx serves src/dash/static and proxies /api/ and /github/ to `dash serve`.
# Build from the repo root: docker build -f webui/Dockerfile -t dash-webui .
# Run:   docker run --rm -p 127.0.0.1:8080:8080 -e DASH_API_URL=http://host.docker.internal:8000 dash-webui

# Unprivileged variant: runs as uid 101 and listens on 8080, not 80.
FROM node:24-alpine AS loopy
WORKDIR /loopy
COPY webui/loopy/package.json webui/loopy/package-lock.json ./
RUN npm ci
COPY webui/loopy/tsconfig.json ./
COPY webui/loopy/src ./src
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine

# The entrypoint renders /etc/nginx/templates/*.template with envsubst into conf.d/.
# Only DASH_API_URL is substituted, so nginx's own $variables stay as they are.
ENV DASH_API_URL=http://dash-api:80 \
    NGINX_ENVSUBST_FILTER=^DASH_

COPY webui/default.conf.template /etc/nginx/templates/default.conf.template
COPY src/dash/static/index.html /usr/share/nginx/html/index.html
COPY src/dash/static/ /usr/share/nginx/html/static/
COPY --from=loopy /loopy/dist/ /usr/share/nginx/html/static/loopy/

EXPOSE 8080
