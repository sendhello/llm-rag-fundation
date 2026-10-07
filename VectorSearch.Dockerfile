FROM python:3.12-slim
WORKDIR /app
COPY uv.lock pyproject.toml ./
RUN pip install uv && uv sync
COPY . .
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
