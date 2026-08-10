# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS build
WORKDIR /app

# Pinning the package manager before the manifests keeps this layer out of the
# way of every source change
RUN corepack enable && corepack prepare pnpm@10.6.2 --activate

COPY package.json pnpm-lock.yaml ./
RUN --mount=type=cache,target=/pnpm-store \
    pnpm config set store-dir /pnpm-store && \
    pnpm install --frozen-lockfile

COPY . .
# The tag is not available inside the build context, so CI passes it in. It sits
# here because it changes on every release and must not reach the install layer
ARG APP_VERSION=""
ENV APP_VERSION=$APP_VERSION
RUN pnpm run build

FROM alpine:3.21
RUN apk add --no-cache nginx nginx-mod-http-brotli && mkdir -p /run/nginx
COPY nginx.conf /etc/nginx/http.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
