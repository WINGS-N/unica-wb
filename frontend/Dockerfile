FROM node:22-alpine AS build
WORKDIR /app
COPY package.json /app/package.json
RUN corepack enable && corepack prepare pnpm@10.6.2 --activate
RUN pnpm install --no-frozen-lockfile
COPY . /app
RUN pnpm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
