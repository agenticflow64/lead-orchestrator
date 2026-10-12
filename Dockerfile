FROM python:3.12-slim

WORKDIR /srv/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN mkdir -p /srv/app/data
ENV DB_PATH=/srv/app/data/leads.db \
    NOTIFICATIONS_LOG=/srv/app/data/notifications.log

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
