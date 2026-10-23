# One image for both services (spec I.1, I.2): the API runs uvicorn, the UI runs streamlit.
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    HF_HOME=/opt/hf-cache

# CPU-only torch first: the default Linux wheel bundles CUDA and is several GB larger.
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

# Download the embedding model at build time, so /ingest and /ask never stall on it.
RUN python scripts/warmup.py

EXPOSE 8000 8501
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
