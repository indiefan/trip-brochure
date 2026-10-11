FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "fastapi>=0.110" "uvicorn[standard]>=0.29" "pydantic>=2"
COPY server.py .
ENV DEPOT_DATA=/data
EXPOSE 8137
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8137"]
