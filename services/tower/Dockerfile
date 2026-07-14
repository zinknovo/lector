FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models/huggingface

WORKDIR /service
COPY services/tower/requirements.txt /service/requirements.txt
RUN pip install --no-cache-dir -r /service/requirements.txt
COPY services/tower/app.py /service/app.py

EXPOSE 8001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
