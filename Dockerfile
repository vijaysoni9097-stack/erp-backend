FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements-hosting.txt ./
RUN pip install --no-cache-dir -r requirements-hosting.txt
COPY app ./app
RUN useradd --uid 10001 --create-home pharmacy && mkdir /data && chown pharmacy:pharmacy /data
USER pharmacy
ENV DATABASE_URL=sqlite:////data/pharmacy.db DEBUG=false PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
