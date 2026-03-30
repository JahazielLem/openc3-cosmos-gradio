FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    software-properties-common \
    wget \
    gnupg \
    && add-apt-repository ppa:gnuradio/gnuradio-releases \
    && apt-get update \
    && apt-get install -y \
        gnuradio \
        gnuradio-dev \
        gr-osmosdr \
        python3-pybind11 \
        libboost-all-dev \
        cmake \
        git \
        libusb-1.0-0-dev \
        libfftw3-dev \
        swig \
        python3-numpy \
        python3-pip \
        python3-requests \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

COPY . .

RUN pip install --no-cache-dir zmq spacepackets --break-system-packages

CMD ["python3","-u", "./bridge.py"]
STOPSIGNAL SIGTERM