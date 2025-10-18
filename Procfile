web: gunicorn app:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:${PORT:-8000} --log-level info

