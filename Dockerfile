# Use an official Python image
FROM ghcr.io/astral-sh/uv:python3.14-bookworm

# Install necessary dependencies and tools
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    tmuxinator \
    tmux \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && wget https://dl.min.io/server/minio/release/linux-amd64/minio -O /usr/local/bin/minio \
    && chmod +x /usr/local/bin/minio \
    && curl -fsSL https://ollama.com/install.sh | sh \
    && curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to /usr/local/bin

# Set the working directory in the container
WORKDIR /app

# Copy the files and directories from the host to the container
COPY . .

# Set up the virtual environment using the `uv` command
RUN uv sync

# Clean up any unnecessary files or caches
RUN rm -rf /root/.cache

# ----------- expose ports -----------
# Stable Diffusion
EXPOSE 7860
# Minio
EXPOSE 9000
# Minio admin
EXPOSE 44983
# Phoenix via HTTP
EXPOSE 6006
# Ollama
EXPOSE 11434
# Chatbot itself
EXPOSE 8000
## Phoenix via gRPC
# EXPOSE 4317

# https://github.com/ollama/ollama/issues/7046#issuecomment-2383792234
ARG MODELS="nomic-embed-text"
ENV OLLAMA_KEEP_ALIVE=24h
RUN ollama serve & server=$! ; sleep 5 ; for m in $MODELS ; do ollama pull $m ; done ; kill $server

# Set the default command to a shell for interactive use
CMD ["just", "serve-all"]
