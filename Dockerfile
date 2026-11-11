FROM python:3.11-slim-bookworm AS backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SAHER_API_PORT=8765 \
    SAHER_OCR_ENGINE=tesseract \
    SAHER_OCR_MODEL_DIR=/opt/saher-models/tessdata \
    SAHER_OCR_LANGUAGES=fas+eng \
    TESSDATA_PREFIX=/opt/saher-models/tessdata

WORKDIR /app

# Install Tesseract OCR 5 engine and Persian/English language bundles during build
# so containers can execute 100% offline without internet access.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-fas \
    tesseract-ocr-eng \
    fonts-dejavu-core \
    libraqm0 \
    libfreetype6 \
    libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY services ./services

# Store offline OCR models in /opt/saher-models/tessdata as well as /app/data/models/tessdata
# so mounting a persistent Docker volume on /app/data never shadows the traineddata files.
RUN mkdir -p /opt/saher-models/tessdata /app/data/models/tessdata && \
    for lang in fas eng osd; do \
      if [ -f "/app/data/models/tessdata/${lang}.traineddata" ]; then \
        cp "/app/data/models/tessdata/${lang}.traineddata" "/opt/saher-models/tessdata/${lang}.traineddata"; \
      elif [ -f "/usr/share/tesseract-ocr/5/tessdata/${lang}.traineddata" ]; then \
        cp "/usr/share/tesseract-ocr/5/tessdata/${lang}.traineddata" "/opt/saher-models/tessdata/${lang}.traineddata"; \
        cp "/usr/share/tesseract-ocr/5/tessdata/${lang}.traineddata" "/app/data/models/tessdata/${lang}.traineddata"; \
      fi; \
    done

RUN pip install --no-cache-dir -e .

EXPOSE 8765

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8765"]


FROM node:22-alpine AS web-build

WORKDIR /app

COPY package.json ./
COPY package-lock.json ./
COPY scripts ./scripts
COPY apps/web/package.json ./apps/web/package.json

RUN npm ci

COPY apps/web ./apps/web

RUN npm run build


FROM nginx:1.27-alpine AS web

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=web-build /app/dist /usr/share/nginx/html

EXPOSE 80
