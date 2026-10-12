# WaferAI 화면 이미지 — 정적 파일을 빌드해 Nginx 로 낸다.
# Nginx 설정은 이미지에 넣지 않고 deploy/compose.yaml 이 붙인다.
# 설정만 고칠 때 다시 빌드하지 않아도 되도록.

FROM node:22-alpine AS build
WORKDIR /app
# 의존성 목록이 그대로면 이 층을 캐시에서 재사용해 빌드가 빨라진다
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.28-alpine
COPY --from=build /app/dist /usr/share/nginx/html
