# ============================================================
# Dockerfile — SaaS Planillas GCP
# Desplegado en: Google Cloud Run
# Base de Datos: Neon (PostgreSQL Serverless)
# ============================================================

FROM python:3.11-slim

# Directorio de trabajo dentro del contenedor
WORKDIR /app

# Dependencias del sistema necesarias para psycopg2 (driver PostgreSQL)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python primero (aprovecha cache de Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente al contenedor
COPY . .

# Cloud Run inyecta la variable PORT (por defecto 8080)
ENV PORT=8080

# Deshabilitar el sistema de reporte de telemetría de Streamlit
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Comando de inicio: Streamlit escucha en 0.0.0.0 para ser accesible desde Cloud Run
CMD ["sh", "-c", "streamlit run presentation/app.py \
    --server.port=${PORT} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false"]
