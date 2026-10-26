FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY agent_engine ./agent_engine
RUN pip install --no-cache-dir . && \
    groupadd --system agentos && useradd --system --gid agentos agentos && \
    mkdir /data && chown agentos:agentos /data
USER agentos
ENV AGENTOS_DATA_DIR=/data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" || exit 1
CMD ["agentos", "serve", "--host", "0.0.0.0", "--port", "8000"]
