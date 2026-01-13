#!/usr/bin/env python3
"""
Standalone replica of ns3::BurstyApplication.

The script reads bursts from one of the burst generators provided in
`burst_generators.py`, fragments them exactly like the ns-3 application,
adds the SeqTsSizeFragHeader metadata, and transmits the resulting
packets over UDP towards a user-provided destination.
"""

from __future__ import annotations

import argparse
import socket
import struct
import time
from typing import Optional, Tuple

from burst_generators import (
    TraceFileBurstGenerator,
    VrAppName,
    VrBurstGenerator,
    available_vr_apps,
)

# Wire-format constants (mirroring SeqTsSizeFragHeader)
SEQTS_SIZE_FRAG_HEADER_LEN = 24  # bytes
HEADER_STRUCT = struct.Struct("!HHQIQ")  # fragSeq, frags, burstSize, seq, timestamp(ns)


def build_header(
    frag_seq: int, total_frags: int, burst_payload: int, burst_seq: int
) -> Tuple[bytes, int]:
    timestamp = time.time_ns()
    return (
        HEADER_STRUCT.pack(frag_seq, total_frags, burst_payload, burst_seq, timestamp),
        timestamp,
    )


def fragment_burst(burst_size: int, fragment_size: int) -> Tuple[int, list]:
    """
    Match ns3::BurstyApplication::SendFragmentedBurst.

    Returns the burst payload size (excluding headers) and the list of
    fragment payload lengths (each excluding the header).
    """

    if burst_size < SEQTS_SIZE_FRAG_HEADER_LEN:
        raise ValueError("Burst size must be at least the header size")
    if fragment_size < SEQTS_SIZE_FRAG_HEADER_LEN:
        raise ValueError("Fragment size must be at least the header size")

    num_full_frags = burst_size // fragment_size
    last_frag_size = burst_size % fragment_size

    second_to_last_size = 0
    if num_full_frags > 0:
        second_to_last_size = fragment_size
        num_full_frags -= 1

    if (
        second_to_last_size > 0
        and last_frag_size > 0
        and last_frag_size < SEQTS_SIZE_FRAG_HEADER_LEN
    ):
        second_to_last_size = fragment_size + last_frag_size - SEQTS_SIZE_FRAG_HEADER_LEN
        last_frag_size = SEQTS_SIZE_FRAG_HEADER_LEN

    if second_to_last_size and second_to_last_size < SEQTS_SIZE_FRAG_HEADER_LEN:
        raise ValueError("Second-to-last fragment would be too small")
    if last_frag_size and last_frag_size < SEQTS_SIZE_FRAG_HEADER_LEN:
        raise ValueError("Last fragment would be too small")

    fragments = []
    full_payload = fragment_size - SEQTS_SIZE_FRAG_HEADER_LEN
    fragments.extend([full_payload] * num_full_frags)
    if second_to_last_size:
        fragments.append(second_to_last_size - SEQTS_SIZE_FRAG_HEADER_LEN)
    if last_frag_size:
        fragments.append(last_frag_size - SEQTS_SIZE_FRAG_HEADER_LEN)

    total_frags = len(fragments)
    burst_payload = burst_size - SEQTS_SIZE_FRAG_HEADER_LEN * total_frags
    return burst_payload, fragments


def format_addr(addr: Tuple[str, int]) -> str:
    return f"{addr[0]}:{addr[1]}"


def log_burst_tx(
    burst_seq: int,
    burst_payload: int,
    total_frags: int,
    local_addr: Tuple[str, int],
    remote_addr: Tuple[str, int],
    timestamp_ns: int,
):
    send_time = timestamp_ns / 1e9
    print(
        f"[BurstTx] Sent burst seq={burst_seq} payload={burst_payload} B "
        f"({total_frags} fragments) from {format_addr(local_addr)} "
        f"to {format_addr(remote_addr)} at {send_time:.9f}s"
    )


def log_fragment_tx(
    frag_seq: int,
    total_frags: int,
    burst_seq: int,
    burst_payload: int,
    fragment_size: int,
    local_addr: Tuple[str, int],
    remote_addr: Tuple[str, int],
    timestamp_ns: int,
):
    send_time = timestamp_ns / 1e9
    print(
        f"[FragmentTx] Sent fragment {frag_seq}/{total_frags} of burst seq={burst_seq} "
        f"payload={burst_payload} B (fragment size={fragment_size} B) "
        f"from {format_addr(local_addr)} to {format_addr(remote_addr)} "
        f"at {send_time:.9f}s"
    )


def run_trace_generator(args: argparse.Namespace):
    return TraceFileBurstGenerator(args.trace_file, start_time=args.start_time)


def run_vr_generator(args: argparse.Namespace):
    app = VrAppName(args.vr_app)
    rate_bps = args.target_rate_mbps * 1e6
    return VrBurstGenerator(app_name=app, frame_rate=args.frame_rate, target_data_rate_bps=rate_bps)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send VR bursts over UDP using the same logic as ns3::BurstyApplication"
    )
    parser.add_argument("--remote-host", required=True, help="Destination IP address")
    parser.add_argument("--remote-port", type=int, required=True, help="Destination UDP port")
    parser.add_argument(
        "--fragment-size",
        type=int,
        default=1200,
        help="Fragment size in bytes (includes header, default: 1200)",
    )
    parser.add_argument(
        "--max-bursts",
        type=int,
        default=None,
        help="Stop after sending this many bursts (default: run until generator is exhausted)",
    )
    parser.add_argument(
        "--generator",
        choices=("trace", "vr"),
        default="trace",
        help="Traffic model to use",
    )
    parser.add_argument("--trace-file", help="CSV trace used by TraceFileBurstGenerator")
    parser.add_argument(
        "--start-time",
        type=float,
        default=0.0,
        help="Start time offset when using the trace generator (seconds)",
    )
    parser.add_argument(
        "--vr-app",
        choices=list(available_vr_apps()),
        default=VrAppName.VirusPopper.value,
        help="VR application profile",
    )
    parser.add_argument(
        "--frame-rate",
        type=float,
        default=60.0,
        choices=(30.0, 60.0),
        help="Frame rate for the VR model",
    )
    parser.add_argument(
        "--target-rate-mbps",
        type=float,
        default=20.0,
        help="Target VR bitrate in Mbps",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.generator == "trace":
        if not args.trace_file:
            raise SystemExit("--trace-file is required when generator=trace")
        generator = run_trace_generator(args)
    else:
        generator = run_vr_generator(args)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", 0))
    destination = (args.remote_host, args.remote_port)

    burst_seq = 0
    bursts_sent = 0
    while generator.has_next_burst():
        burst_size, period = generator.generate_burst()
        if burst_size < SEQTS_SIZE_FRAG_HEADER_LEN:
            continue
        burst_payload, fragment_payloads = fragment_burst(burst_size, args.fragment_size)
        total_frags = len(fragment_payloads)
        payload_buffer = bytearray(burst_payload)
        local_addr = sock.getsockname()
        burst_log_ts = time.time_ns()
        log_burst_tx(burst_seq, burst_payload, total_frags, local_addr, destination, burst_log_ts)
        offset = 0
        for frag_idx, payload_len in enumerate(fragment_payloads):
            fragment = payload_buffer[offset : offset + payload_len]
            offset += payload_len
            header_bytes, frag_timestamp = build_header(
                frag_idx, total_frags, burst_payload, burst_seq
            )
            packet = header_bytes + fragment
            sock.sendto(packet, destination)
            log_fragment_tx(
                frag_idx,
                total_frags,
                burst_seq,
                burst_payload,
                len(packet),
                local_addr,
                destination,
                frag_timestamp,
            )
        burst_seq += 1
        bursts_sent += 1
        if args.max_bursts is not None and bursts_sent >= args.max_bursts:
            break
        if period > 0:
            time.sleep(period)


if __name__ == "__main__":
    main()
