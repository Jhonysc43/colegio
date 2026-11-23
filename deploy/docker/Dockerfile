# Alternativa em contêiner (Linux com Docker). Construir na pasta do sistema:
#   docker build -f deploy/docker/Dockerfile -t receita-cnb .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    CLOUD_FINANCE_DB=/dados/cloud_finance.db \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY core ./core
COPY ui ./ui
COPY scripts ./scripts
COPY .streamlit ./.streamlit

RUN useradd --create-home --uid 1000 receitacnb && mkdir -p /dados && chown receitacnb /dados
USER receitacnb
VOLUME ["/dados"]
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health').read()==b'ok' else 1)"

CMD ["python", "-m", "streamlit", "run", "app.py"]
