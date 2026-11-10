FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY data ./data
COPY documents ./documents
COPY scripts ./scripts
# Normalize Windows CRLF line endings before running shell scripts in Linux containers.
RUN sed -i 's/\r$//' scripts/*.sh && chmod +x scripts/*.sh
COPY ui ./ui
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["uvicorn", "kyc_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
