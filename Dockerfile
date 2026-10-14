FROM python:3.12-slim

# git is needed to clone the repositories that are analysed
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY datasets ./datasets
ENV CODEDNA_DATA=/data
EXPOSE 8000
CMD ["python", "-m", "codedna", "serve", "--host", "0.0.0.0", "--port", "8000"]
