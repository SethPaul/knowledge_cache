# Use the official pgvector image as base
FROM pgvector/pgvector:pg16

# Install additional utilities if needed
RUN apt-get update && \
    apt-get install -y \
    postgresql-contrib \
    && rm -rf /var/lib/apt/lists/*

# Copy initialization scripts
COPY ./docker/postgres/init/ /docker-entrypoint-initdb.d/

# Ensure proper permissions
RUN chmod +x /docker-entrypoint-initdb.d/*.sh 