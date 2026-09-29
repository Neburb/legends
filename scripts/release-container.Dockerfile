FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN git config --system --add safe.directory /source
USER 65534:65534
WORKDIR /tmp
