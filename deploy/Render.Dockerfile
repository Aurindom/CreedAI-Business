FROM mcr.microsoft.com/playwright/python:v1.64.1-noble
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
WORKDIR /srv/backend
RUN pip install --no-cache-dir playwright==1.64.1 fastapi==0.162.2 uvicorn==0.54.0 httpx==0.28.1
COPY backend/app/render_service.py /srv/backend/render_service.py
RUN chmod a+r /srv/backend/render_service.py
USER pwuser
EXPOSE 8081
CMD ["python","-m","uvicorn","render_service:app","--host","0.0.0.0","--port","8081","--workers","1","--no-access-log"]
