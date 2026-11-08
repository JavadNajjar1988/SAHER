FROM node:22-alpine AS frontend
WORKDIR /app
COPY package*.json ./
COPY apps/web apps/web
RUN npm ci --no-audit --no-fund && npm run build

FROM python:3.12-slim AS backend
WORKDIR /app
COPY pyproject.toml README.md ./
COPY services services
RUN pip install --no-cache-dir .
CMD ["python", "-m", "uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8765"]

FROM nginx:1.27-alpine AS web
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend /app/apps/web/dist /usr/share/nginx/html
