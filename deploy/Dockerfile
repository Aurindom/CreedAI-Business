FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FRONTEND_DIST=/srv/frontend
RUN useradd --system --uid 10001 --home-dir /nonexistent penny
WORKDIR /srv/backend
COPY backend/requirements.txt backend/requirements-mcp.txt ./
RUN pip install --no-cache-dir -r requirements-mcp.txt
COPY backend/app ./app
COPY backend/data/catalog.json ./data/catalog.json
COPY --from=ui /ui/dist /srv/frontend
USER penny
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
