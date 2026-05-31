FROM python:3.12-slim
WORKDIR /app
COPY poetry.lock pyproject.toml ./
RUN pip install poetry && poetry config virtualenvs.create false && poetry install --no-root
COPY . .
EXPOSE 8000
CMD ["poetry", "run", "python", "vector_search.py"]
