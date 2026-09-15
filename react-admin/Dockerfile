# Builds the React admin and serves the static bundle with nginx.
# Build context: this react-admin/ directory.
FROM node:20-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# VITE_API_BASE defaults to /api/v1 (same-origin); nginx proxies /api to the API.
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
