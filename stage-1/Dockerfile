FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /srv

# Every runtime dependency is installed here; the container needs no network at run time.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

RUN useradd --system --no-create-home pocketful
USER pocketful

EXPOSE 8080
CMD ["python", "-m", "app"]
