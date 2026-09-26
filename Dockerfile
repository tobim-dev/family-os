FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FOS_DB=/data/family.sqlite
LABEL org.opencontainers.image.source="https://github.com/tobim-dev/family-os"
LABEL org.opencontainers.image.title="Family OS"
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home family && mkdir /data && chown family:family /data
COPY --chown=family:family app.py integrations.py meals.py migrations.py nanny.py recipe_images.py meal_suggestions.py shopping_week.py meal_reminders.py closures.py backups.py manage.py docker-entrypoint.py ./
COPY --chown=family:family static ./static
USER family
ENTRYPOINT ["python", "/app/docker-entrypoint.py"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
