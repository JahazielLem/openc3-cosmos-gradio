#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# SPDX-License-Identifier: GPL-3.0
#
# Title: Bridge Data Interface
# Author: Kevin Leon
# Copyright: pwnsat.org
# Description: GNU Radio to CosmosC3 Communication Interface

import zmq
import sys
import pmt
import time
import socket
import struct
import signal
import string
import threading
from spacepackets.ccsds.spacepacket import SpHeader, PacketType, CCSDS_HEADER_LEN

SOFTWARE_VERSION = "0.1.0"
BANNER = f"""
  +-------------+        +-------------+        +-------------+        +-------------+
  |   PWNSAT    |  RF    |     SDR     |  IQ    |     BDI     |  UDP   |   OpenC3    |
  | --|    |--  | ~~~~~> |    (~~)     | -----> |    [==>]    | -----> |   [GUI]     |
  |   |____|    |        |  RF Front   |        |  SPP Decode |        |  Mission    |
  |  Telemetry  |        |  LoRa Demod |        |   Routing   |        |  Control    |
  |   Telecmd   |        |             |        |             |        |             |
  +-------------+        +-------------+        +-------------+        +-------------+

  \033[36mBridge Data Inferface | Version: {SOFTWARE_VERSION} | Author: Kevin Leon | Pwnsat\033[0m
"""

LISTEN_IP = "0.0.0.0"
COMMAND_PORT = 1235
TELEMETRY_PORT = 1234
# Change if the client is on a different machine
TELEMETRY_IP = "cosmos-project-openc3-operator-1"

# GNU Radio
GRADIO_TM_SERVER = "tcp://172.18.0.1:5005"
GRADIO_TC_SERVER = "tcp://172.18.0.1:5006"

def ok(msg): print(f"\033[32m[+]\033[0m {msg}")
def err(msg): print(f"\033[31m[!]\033[0m {msg}")
def info(msg): print(f"\033[34m[*]\033[0m {msg}")

TLM_IDS = {
    "SPAYLOAD": 0x4320
}

def hexdump(data: bytes, width: int = 16) -> str:
    lines = []

    for offset in range(0, len(data), width):
        chunk = data[offset : offset + width]

        hex_bytes = " ".join(f"{b:02X}" for b in chunk)
        hex_bytes = hex_bytes.ljust(width * 3)

        ascii_bytes = "".join(
            chr(b) if chr(b) in string.printable and b >= 0x20 else "." for b in chunk
        )

        lines.append(f"{offset:08X}  {hex_bytes}  {ascii_bytes}")

    return "\n".join(lines)

def hexdump_split(data: bytes, header_len=6):
    header = data[:header_len]
    payload = data[header_len:]

    print("\033[33m[HEADER]\033[0m")
    print(hexdump(header))

    print("\033[36m[PAYLOAD]\033[0m")
    print(hexdump(payload))

def print_packet(packet: bytes, name: str = "PACKET") -> None:
    print(f"\n=========== {name} ===========")
    print(f"Length: {len(packet)}")
    print(hexdump(packet))


class SpacePacketCounter:
    def __init__(self):
        self.tc_counter = 0
    
    def tc_update(self):
        self.tc_counter += 1
    
    def tc_get_counter(self):
        return self.tc_counter

class SpacePacketProtocolEncoder:
    def __init__(self, apid = 0x01, raw_frame: bytes = None, counter: int = 0):
        self.raw_frame = raw_frame
        self.apid = apid
        self.counter = counter

    def encode(self):
        tc_header = SpHeader.tc(apid=self.apid, seq_count=self.counter, data_len=0)
        if len(self.raw_frame) > 0:
            if len(self.raw_frame) == 1:
                self.raw_frame = self.raw_frame + b"0"
            tc_header.set_data_len_from_packet_len(CCSDS_HEADER_LEN + len(self.raw_frame))
            telecommand = tc_header.pack()
            telecommand.extend(self.raw_frame)
        else:
            telecommand = tc_header.pack()
        return telecommand

class SpacePacketProtocolDecoder:
    def __init__(self, raw_frame: bytes = None):
        self.raw_frame = raw_frame
        self.packet_id = 0
        self.sequence = 0
        self.length = 0
        self.version = 0
        self.f_type = 0
        self.sec_header = 0
        self.apid = 0
        self.seq_flags = 0
        self.seq_count = 0
        self.seq_flag_str = "Unknown"
        self.payload = None


    def decode(self) -> bool:
        if self.raw_frame is None:
            return False
        
        if len(self.raw_frame) < 6:
            err("Space Packet to short")
            return False
        
        (self.packet_id, self.sequence, self.length) = struct.unpack(">HHH", self.raw_frame[:6])

        self.version    = (self.packet_id >> 14) & 0x7
        self.f_type     = (self.packet_id >> 12) & 0x1
        self.sec_header = (self.packet_id >> 11) & 0x1
        self.apid       = self.packet_id & 0x7FF

        self.seq_flags = (self.sequence >> 14) & 0x3
        self.seq_count = self.sequence & 0x3FFF

        self.payload = self.raw_frame[6:6 + (self.length + 1)]

        self.seq_flag_str = {
            0b00: "Continuation",
            0b01: "Start",
            0b10: "End",
            0b11: "Unsegmented"
        }.get(self.seq_flags, "Unknown")
        
        return True
    
    def print_details(self):
        print(f"\n=========== Space Packet ===========")
        print(f"Version:            {self.version}")
        print(f"Type:               {self.f_type:02X} ({'TM' if self.f_type == 0x00 else 'TC'})")
        print(f"Secondary Header:   {self.sec_header}")
        print(f"APID:               0x{self.apid:04X}")
        print(f"Sequence Flags:     0x{self.seq_flags:X} ({self.seq_flag_str})")
        print(f"Sequence Count:     {self.seq_count}")
        print(f"Data Length:        {self.length}")
        hexdump_split(self.raw_frame)
    
    def print_summary(self):
        print(
            f"\033[36m[TM - SPP]\033[0m "
            f"APID=0x{self.apid:03X} "
            f"SEQ={self.seq_count} SEQ_FLAG={self.seq_flag_str} "
            f"LEN={self.length} "
            f"TYPE={'TM' if self.f_type == 0 else 'TC'} "
            f"FLAGS={self.seq_flags}")

class GNURadioController:
    def __init__(self):
        self.tm_ctx = None
        self.tm_sock = None
        self.tc_ctx = None
        self.tc_sock = None
        self.running = False
        self.cb_packet = None
        self.spp_counter = SpacePacketCounter()

    def set_cb_packet(self, cb):
        self.cb_packet = cb
    
    def start(self):
        self.running = True
        self.tm_ctx = zmq.Context()
        self.tm_sock = self.tm_ctx.socket(zmq.SUB)
        self.tc_ctx = zmq.Context()
        self.tc_sock = self.tc_ctx.socket(zmq.PUSH)

        ok("Connecting to GNU Radio TM server")
        self.tm_sock.connect(GRADIO_TM_SERVER)
        self.tm_sock.setsockopt(zmq.SUBSCRIBE, b"")

        ok("Connecting to GNU Radio TC server")
        self.tc_sock.connect(GRADIO_TC_SERVER)
        self.tc_sock.setsockopt(zmq.SNDHWM, 1)
    
    def send_tc(self, command: bytes):
        apid = command[1]
        payload = command[2:]
        b_spp = SpacePacketProtocolEncoder(apid, payload, self.spp_counter.tc_get_counter()).encode()
        
        print(
            f"\033[33m[TC - SPP]\033[0m "
            f"APID=0x{apid:03X} "
            f"SEQ={self.spp_counter.tc_get_counter()} "
            f"LEN={len(b_spp)} "
            f"TYPE=TC ")
        
        for i in range(0, 6):
            pdu_bytes = pmt.serialize_str(pmt.to_pmt(b_spp.hex()))
            self.tc_sock.send(pdu_bytes)
            time.sleep(1)
        
        self.spp_counter.tc_update()

    def stop(self):
        if not self.running:
            return
        
        self.running = False
        
        info("\nStooping...")
        if self.tm_sock:
            self.tm_sock.close(0)
        
        if self.tm_ctx:
            self.tm_ctx.term()
        
        if self.tc_sock:
            self.tc_sock.close(0)
        
        if self.tc_ctx:
            self.tc_ctx.term()
        ok("Clean exit")
    
    def run(self):
        self.start()
        try:
            while self.running:
                raw_telemetry = self.tm_sock.recv()
                spp = SpacePacketProtocolDecoder(raw_telemetry)
                if spp.decode():
                    spp.print_summary()
                    if self.cb_packet:
                        self.cb_packet(spp)
        except KeyboardInterrupt:
            self.stop()

class DockerController:
    def __init__(self):
        self.tc_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.tm_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.running = False

        self.sender_cb = None

    def set_sender_cb(self, cb):
        self.sender_cb = cb
    
    def setup(self):
        self.tc_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.tm_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def start(self):
        self.running = True
        self.tc_socket.bind((LISTEN_IP, COMMAND_PORT))

        ok("BDI TC server binded")

    def send_telemetry(self, spp_packet: SpacePacketProtocolDecoder):
        packed = struct.pack("<h", spp_packet.apid) + spp_packet.payload
        self.tm_socket.sendto(packed, (TELEMETRY_IP, TELEMETRY_PORT))
    
    def run(self):
        def handler(sig, frame):
            self.stop()
            sys.exit(0)
            
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

        self.setup()
        self.start()

        while self.running:
            try:
                data, addr = self.tc_socket.recvfrom(1024)
                print_packet(data, "COMMAND")
                # Response to Cosmos Site
                id = TLM_IDS["SPAYLOAD"]
                fmt = '>h12s'
                packed = struct.pack(fmt, id, b"RSP")
                self.tm_socket.sendto(packed, (TELEMETRY_IP, TELEMETRY_PORT))
                # Send to SDR
                if self.sender_cb:
                    self.sender_cb(data)
            except KeyboardInterrupt:
                self.stop()
    
    def stop(self):
        info("\nShutting down sockets...")
        if not self.running:
            return
        
        self.running = False
        
        if self.tc_socket:
            self.tc_socket.close()
        
        ok("Clear stop!")

def show_banner():
    print(BANNER)

def main():
    show_banner()
    gradio = GNURadioController()
    dcontroller = DockerController()
    
    gradio.set_cb_packet(dcontroller.send_telemetry)
    dcontroller.set_sender_cb(gradio.send_tc)

    th_gradio = threading.Thread(target=gradio.run, daemon=True)
    th_gradio.start()

    dcontroller.run()

    gradio.stop()

    if th_gradio.is_alive():
        th_gradio.join()

if __name__ == "__main__":
    main()
