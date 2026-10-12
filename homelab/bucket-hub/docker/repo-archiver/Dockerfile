FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git git-lfs \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY repo_archiver_entry.py /app/repo_archiver_entry.py
ENTRYPOINT ["python3", "/app/repo_archiver_entry.py"]
