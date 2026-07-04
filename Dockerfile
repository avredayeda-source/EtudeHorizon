FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# Railway (y otros PaaS) inyectan el puerto via $PORT. Usamos la forma shell
# para que ${PORT} se expanda; si no existe, cae a 8000 (local).
CMD ["sh", "-c", "uvicorn agent.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
