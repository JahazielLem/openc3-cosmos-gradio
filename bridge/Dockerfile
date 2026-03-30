# Use an official Python runtime as a parent image
FROM python:3.8-slim

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy the current directory contents into the container at /usr/src/app
COPY . .

RUN pip install --no-cache-dir zmq spacepackets

# Run the server when the container launches
CMD ["python","-u", "./bridge.py"]
STOPSIGNAL SIGTERM