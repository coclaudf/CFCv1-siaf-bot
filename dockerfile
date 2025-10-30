# ===========================================================
# Dockerfile para chatbot SIAF (Python + Telegram + Gemini)
# Optimizado para Render
# ===========================================================

# Imagen base oficial de Python
FROM python:3.11-slim

# Configuración de entorno
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Crear directorio de trabajo
WORKDIR /app

# Copiar los archivos de proyecto
COPY . /app

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Exponer el puerto (Render requiere que haya uno definido, aunque use polling)
EXPOSE 8080

# Comando de ejecución
CMD ["python", "main.py"]
