web: gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --worker-class gthread --threads 8 --timeout ${GUNICORN_TIMEOUT:-$(if [ "${STAND_MODE:-0}" = "1" ]; then echo 180; else echo 120; fi)}
