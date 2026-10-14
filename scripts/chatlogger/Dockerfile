FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir aiohttp
COPY scripts/chatlogger/logger.py scripts/chatlogger/logger.py
# весь volume data/ монтируется снаружи (sqlite + дневные логи)
CMD ["python3", "scripts/chatlogger/logger.py"]
