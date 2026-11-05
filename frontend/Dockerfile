# LearnSense frontend: production build with the existing Vite tooling, served by nginx.
# Build from the repository root:
#   docker build -f frontend/Dockerfile \
#     --build-arg SUPABASE_URL=... --build-arg SUPABASE_PUBLISHABLE_KEY=... \
#     --build-arg VITE_API_BASE_URL=https://api.example.edu/api -t learnsense-web .
# Only PUBLIC values belong here (vite.config.ts exposes nothing else to the browser).
FROM node:22-alpine AS build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ARG SUPABASE_URL=""
ARG SUPABASE_PUBLISHABLE_KEY=""
ARG VITE_API_BASE_URL=""
ENV SUPABASE_URL=$SUPABASE_URL \
    SUPABASE_PUBLISHABLE_KEY=$SUPABASE_PUBLISHABLE_KEY \
    VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY deploy/nginx/frontend.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/frontend/dist /usr/share/nginx/html
EXPOSE 80
