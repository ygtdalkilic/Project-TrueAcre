# Stage 1: build the dashboard
FROM node:24-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

# Stage 2: the API, serving the built dashboard from web/dist
FROM python:3.14-slim
WORKDIR /app
RUN useradd --create-home app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY api api
COPY engine engine
COPY data data
COPY alembic.ini .
COPY migrations migrations
COPY --from=web /web/dist web/dist
USER app
ENV TRUEACRE_ENV=production PORT=8080
# --proxy-headers: trust X-Forwarded-* from Cloud Run's load balancer so scheme and client IP are right
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
