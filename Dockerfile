FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SAHER_OCR_ENGINE=tesseract \
    SAHER_OCR_MODEL_DIR=/app/data/models/tessdata \
    SAHER_OCR_LANGUAGES=fas+eng \
    TESSDATA_PREFIX=/app/data/models/tessdata

WORKDIR /app

# Install Tesseract OCR engine and Persian/English language bundles during image build
# so runtime containers can execute with network_mode: "none" (100% offline).
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-fas \
    tesseract-ocr-eng \
    libraqm0 \
    libfreetype6 \
    libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY services ./services
COPY data/models ./data/models

# Fallback copy from system tessdata if local model directory is empty
RUN mkdir -p /app/data/models/tessdata && \
    for lang in fas eng osd; do \
      if [ ! -f "/app/data/models/tessdata/${lang}.traineddata" ] && [ -f "/usr/share/tesseract-ocr/5/tessdata/${lang}.traineddata" ]; then \
        cp "/usr/share/tesseract-ocr/5/tessdata/${lang}.traineddata" "/app/data/models/tessdata/${lang}.traineddata"; \
      fi; \
    done

RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
