web: gunicorn --bind 0.0.0.0:$PORT --workers=2 --threads=2 --worker-class=gevent wsgi:app
telegram: python run_telegram_bot.py
