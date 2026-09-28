# Pocketful — stage 1

From the repository root, this builds the image and starts the service on port 8080:

```sh
docker build -t pocketful-stage-1 stage-1 && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-1
```

No other setup is needed. The service listens on `0.0.0.0:$PORT` (default `8080`) and needs
no network access at run time. Check it with `curl http://localhost:8080/health`.

## Unit tests

```sh
cd stage-1
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```
