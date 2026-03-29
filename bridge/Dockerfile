FROM python:3.8-slim

WORKDIR /usr/src/app

COPY . .

RUN pip install --no-cache-dir zmq spacepackets

CMD ["python","-u", "./bridge.py"]
STOPSIGNAL SIGTERM