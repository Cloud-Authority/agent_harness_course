FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /course
COPY part_1/custom_harness/appbook/requirements.txt /tmp/requirements.txt
COPY part_1/custom_harness/appbook/requirements-live.txt /tmp/requirements-live.txt
RUN pip install --no-cache-dir -r /tmp/requirements-live.txt
COPY part_1 ./part_1
WORKDIR /course/part_1/custom_harness/appbook
RUN chmod +x docker-entrypoint.sh
EXPOSE 8000
CMD ["./docker-entrypoint.sh"]
