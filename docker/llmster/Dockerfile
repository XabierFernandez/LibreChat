FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y --no-install-recommends bash curl ca-certificates libatomic1 libgomp1 tini \
  && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
  export HOME=/root; \
  mkdir -p "$HOME"; \
  curl -fsSL https://lmstudio.ai/install.sh -o /tmp/install.sh; \
  bash /tmp/install.sh --no-modify-path; \
  rm -rf /tmp/install.sh

ENV HOME=/root \
    PATH="/root/.lmstudio/bin:${PATH}" \
    LLMSTER_HOME=/root/.lmstudio

COPY docker/llmster/entrypoint.sh /usr/local/bin/llmster-entrypoint

RUN chmod +x /usr/local/bin/llmster-entrypoint

EXPOSE 1234

HEALTHCHECK --interval=30s --timeout=5s --retries=10 --start-period=20s \
  CMD curl -fsS http://127.0.0.1:1234/lmstudio-greeting >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/llmster-entrypoint"]
