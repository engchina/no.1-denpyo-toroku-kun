# Denpyo Toroku Service
# Based on Oracle Linux 8 (reference architecture pattern)
FROM container-registry.oracle.com/os/oraclelinux:8

ARG http_proxy
ARG https_proxy
ARG HTTP_PROXY
ARG HTTPS_PROXY

# Install system dependencies
RUN yum install -y \
    python39 python39-pip python39-devel \
    gcc gcc-c++ make \
    bash vim wget hostname \
    && yum clean all \
    && rm -rf /var/cache/yum

# Clear proxy env after install
ENV http_proxy= \
    https_proxy= \
    HTTP_PROXY= \
    HTTPS_PROXY=

# Create application user
RUN groupadd appuser \
    && useradd appuser -g appuser

# Create application directories
RUN mkdir -p /home/appuser/install/denpyo_toroku/log \
    && mkdir -p /home/appuser/install/denpyo_toroku/models \
    && chown -R appuser:appuser /home/appuser/install

# Copy application files
COPY --chown=appuser:appuser ./denpyo_toroku/ /home/appuser/install/denpyo_toroku/
COPY --chown=appuser:appuser ./gunicorn_config/ /home/appuser/install/gunicorn_config/
COPY --chown=appuser:appuser ./requirements.txt /home/appuser/install/
COPY --chown=appuser:appuser ./requirements.lock /home/appuser/install/

# Install Python dependencies
RUN if [ -f /home/appuser/install/requirements.lock ]; then \
        pip3 install --no-cache-dir -r /home/appuser/install/requirements.lock; \
    else \
        pip3 install --no-cache-dir -r /home/appuser/install/requirements.txt; \
    fi

# OCI config directory
RUN mkdir -p /home/appuser/.oci \
    && chown -R appuser:appuser /home/appuser/.oci

# Switch to application user
USER appuser

# Set working directory
WORKDIR /home/appuser/install/denpyo_toroku

# Expose port (for direct TCP binding mode)
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/v1/health')" || exit 1

# Default command - Gunicorn with config file
CMD ["gunicorn", "-c", "/home/appuser/install/gunicorn_config/gunicorn_config.py"]
