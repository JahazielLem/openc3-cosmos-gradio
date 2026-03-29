#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# SPDX-License-Identifier: GPL-3.0
#
# Title: Bridge Data Interface
# Author: Kevin Leon
# Copyright: pwnsat.org
# Description: SDR to CosmosC3 Communication Interface
import zmq
import socket
import struct
import signal
import threading

SOFTWARE_VERSION = "0.1.0"
BANNER = f"Bridge Data Inferface | Version: {SOFTWARE_VERSION} | Author: Kevin Leon | Pwnsat.org"

LOCAL_IP = "0.0.0.0"
COSMOS_TC_PORT = 5020
COSMOS_TM_PORT = 5010

GDI_TM_PORT = "tcp://0.0.0.0:5005"
GDI_TC_PORT = "tcp://0.0.0.0:5006"

def ok(msg): print(f"\033[32m[+]\033[0m {msg}")
def err(msg): print(f"\033[31m[!]\033[0m {msg}")
def info(msg): print(f"\033[34m[*]\033[0m {msg}")

class GDI:
  def __init__(self):
    self.sdr_gdi_tc    = None
    self.sdr_gdi_tm    = None
    self.gdi_cosmos_tc = None
    self.gdi_cosmos_tm = None
    self.sockets = []

    self.shutdown_event = threading.Event()
    self.zmq_context = zmq.Context()
    signal.signal(signal.SIGINT, self.handle_signal)
    signal.signal(signal.SIGTERM, self.handle_signal)

  def handle_signal(self, signum, _):
    err(f"Signal {signum} received, shutting down...")
    self.shutdown_event.set()

  def send_gdi_sdr_tc(self, pkt: bytes):
    if self.sdr_gdi_tc is None:
      self.sdr_gdi_tc = self.zmq_context.socket(zmq.PUSH)
      self.sdr_gdi_tc.connect(GDI_TC_PORT)
    packet = b"hello world"
    ok(f"Packet sended to: {GDI_TC_PORT} {packet}")
    self.sdr_gdi_tc.send(packet)

  def sdr_tm_recv_worker(self):
    info("GDI thread started")

    poller = zmq.Poller()
    poller.register(self.sdr_gdi_tm, zmq.POLLIN)

    while not self.shutdown_event.is_set():
      try:
        socks = dict(poller.poll(500))
        if self.sdr_gdi_tm in socks:
            data = self.sdr_gdi_tm.recv(zmq.NOBLOCK)
            if data:
              print(f"GDI RECV -> {data}")
      except zmq.ZMQError:
        break
    info("GDI thread exiting")

  def _init_sdr_gdi_tm(self):
    ok(f"Listening ZMQ {GDI_TM_PORT}")
    self.sdr_gdi_tm = self.zmq_context.socket(zmq.PULL)
    self.sdr_gdi_tm.bind(GDI_TM_PORT)
    self.sockets.append(self.sdr_gdi_tm)

  def _init_sdr_gdi_tc(self):
    ok(f"Connected ZMQ {GDI_TC_PORT}")
    self.sdr_gdi_tc = self.zmq_context.socket(zmq.PUSH)
    self.sdr_gdi_tc.connect(GDI_TC_PORT)
    self.sockets.append(self.sdr_gdi_tc)

  def _init_gdi_cosmos_tc(self):
    ok(f"Listening Cosmos TC {COSMOS_TC_PORT}")
    self.gdi_cosmos_tc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.gdi_cosmos_tc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    self.gdi_cosmos_tc.bind((LOCAL_IP, COSMOS_TC_PORT))
    self.gdi_cosmos_tc.settimeout(1.0)
    self.sockets.append(self.gdi_cosmos_tc)

  def _init_gdi_cosmos_tm(self):
    ok(f"Connecting Cosmos TM {COSMOS_TM_PORT}")
    self.gdi_cosmos_tm = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

  def run(self):
    err("Press CTRL + C to exit...")
    print(BANNER)

    try:
      self._init_sdr_gdi_tm()
      self._init_sdr_gdi_tc()
      self._init_gdi_cosmos_tc()

      proxy_td = threading.Thread(target=self.sdr_tm_recv_worker, daemon=False)
      proxy_td.start()

      while not self.shutdown_event.is_set():
        try:
          data, addr = self.gdi_cosmos_tc.recvfrom(1024)
          if data:
            print(f"[{addr}] TC -> {data}")
            self.send_gdi_sdr_tc(data)
        except socket.timeout:
          continue
        except OSError:
          break
    finally:
      err("Shutting down sockets...")
      self.shutdown_event.set()

      proxy_td.join(timeout=1)

      for s in self.sockets:
        try:
            s.close()
        except Exception:
            pass
      self.zmq_context.term()
      ok("Shutdown complete")

if __name__ == "__main__":
  GDI().run()