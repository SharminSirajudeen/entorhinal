# The hosted demo. Standard library only, so the image is the Python base and two folders. Memory lives under
# /tmp: wiped on every restart, and each visitor's file is deleted 24 h after their cookie was issued (app/server.py).
FROM python:3.12-slim
RUN useradd -m -u 1000 user
USER user
WORKDIR /home/user/app
COPY --chown=user app app
COPY --chown=user life life
ENV PYTHONUNBUFFERED=1
EXPOSE 7860
# the host sets PORT (Render: 10000); 7860 elsewhere (Hugging Face)
CMD python -m app.server --host 0.0.0.0 --port "${PORT:-7860}" --dir /tmp/memories
