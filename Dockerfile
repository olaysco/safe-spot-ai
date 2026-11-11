FROM python:3.13-slim
WORKDIR /srv/safespot
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
RUN useradd --create-home safespot
COPY app ./app
RUN mkdir -p .local/uploads && chown -R safespot:safespot /srv/safespot
USER safespot
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
