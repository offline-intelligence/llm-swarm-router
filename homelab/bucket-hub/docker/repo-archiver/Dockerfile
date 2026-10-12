FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git git-lfs \
    && rm -rf /var/lib/apt/lists/*
# Pinned for AP-4 hf_snapshot; bump deliberately and rebuild with a new image tag.
RUN pip install --no-cache-dir huggingface_hub==0.26.2
WORKDIR /app
COPY repo_archiver_entry.py /app/repo_archiver_entry.py
ENTRYPOINT ["python3", "/app/repo_archiver_entry.py"]
