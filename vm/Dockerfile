# Agent ka "computer": base image. Common cheezein pehle se, baaki AI khud install karega.
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    sudo git curl wget ca-certificates build-essential \
    pandoc poppler-utils nodejs npm \
    unzip zip jq ripgrep less nano procps file \
    && rm -rf /var/lib/apt/lists/*

# Python tools jo assignments mein kaam aayenge (baaki AI khud install kar lega)
RUN pip install --no-cache-dir requests pymupdf4llm python-docx openpyxl

# Non-root user + passwordless sudo.
# Abhi loose access: sudo chalta hai. Baad mein tight karna ho toh
# neeche wali sudoers line hata dena, bas.
RUN useradd -m -u 1000 -s /bin/bash agent \
    && echo "agent ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/agent \
    && chmod 0440 /etc/sudoers.d/agent

USER agent
WORKDIR /workspace
CMD ["sleep", "infinity"]
