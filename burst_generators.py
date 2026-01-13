#!/usr/bin/env python3
"""
Standalone replicas of the ns-3 VR burst generators.

The goal is to reproduce the sender-side logic (burst generation and
fragmentation scheduling) outside ns-3 so that the same traffic models
can be used in physical testbeds.
"""

from __future__ import annotations

import csv
import math
import random
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Iterable, Optional, Tuple


class BurstGenerator:
    """Base class mirroring contrib/vr-app/model/burst-generator.h."""

    def generate_burst(self) -> Tuple[int, float]:
        """Return the next burst size [B] and the time before the next one [s]."""

        raise NotImplementedError

    def has_next_burst(self) -> bool:
        """Return True if generate_burst() can be called."""

        raise NotImplementedError


class TraceFileBurstGenerator(BurstGenerator):
    """
    Replica of ns3::TraceFileBurstGenerator.

    Each CSV row must contain two numbers:
      * column 0: burst size in bytes (including headers);
      * column 1: time until the next burst (seconds).
    """

    def __init__(self, trace_file: str, start_time: float = 0.0):
        self._trace_file = trace_file
        self._start_time = float(start_time)
        self._bursts: Deque[Tuple[int, float]] = deque()
        self._trace_duration = 0.0
        self._load_trace()

    def _load_trace(self) -> None:
        cumulative_start = 0.0
        with open(self._trace_file, newline="") as handle:
            reader = csv.reader(handle)
            for row_num, row in enumerate(reader, start=1):
                if not row:
                    continue
                stripped_row = [col.strip() for col in row]
                if not stripped_row[0] or stripped_row[0].startswith("#"):
                    continue
                if all(col == "" for col in stripped_row):
                    continue
                try:
                    burst_size = int(stripped_row[0])
                    period = float(stripped_row[1])
                except (ValueError, IndexError) as exc:
                    raise ValueError(
                        f"Invalid row #{row_num} in {self._trace_file}: {row}"
                    ) from exc
                if period < 0:
                    raise ValueError(
                        f"Period must be non-negative (row #{row_num}, value={period})"
                    )
                if cumulative_start >= self._start_time:
                    self._bursts.append((burst_size, period))
                    self._trace_duration += period
                cumulative_start += period
        if not self._bursts:
            raise ValueError(
                f"No bursts found in {self._trace_file} after start_time={self._start_time}"
            )

    @property
    def trace_duration(self) -> float:
        """Total duration of the imported trace (seconds)."""

        return self._trace_duration

    def has_next_burst(self) -> bool:
        return bool(self._bursts)

    def generate_burst(self) -> Tuple[int, float]:
        if not self._bursts:
            raise RuntimeError("All bursts have been consumed")
        return self._bursts.popleft()


class VrAppName(str, Enum):
    """Names used in the VR traces."""

    VirusPopper = "VirusPopper"
    Minecraft = "Minecraft"
    GoogleEarthVrCities = "GoogleEarthVrCities"
    GoogleEarthVrTour = "GoogleEarthVrTour"


@dataclass(frozen=True)
class _VrModelCoefficients:
    alpha: float
    beta: float
    gamma: Optional[float] = None
    delta: Optional[float] = None
    epsilon: Optional[float] = None


_VR_MODELS = {
    VrAppName.VirusPopper: _VrModelCoefficients(
        alpha=0.17843005544386825,
        beta=-0.24033549,
        gamma=0.03720502322046791,
        delta=0.014333111298430356,
        epsilon=0.17636808,
    ),
    VrAppName.Minecraft: _VrModelCoefficients(
        alpha=0.18570635904452573,
        beta=-0.18721216,
        gamma=0.07132669841811076,
        delta=0.024192743507827373,
        epsilon=0.22666163,
    ),
    VrAppName.GoogleEarthVrCities: _VrModelCoefficients(
        alpha=0.259684566301378,
        beta=-0.25390119,
        gamma=0.034571656202610615,
        delta=0.008953037116942649,
        epsilon=0.3119082,
    ),
    VrAppName.GoogleEarthVrTour: _VrModelCoefficients(
        alpha=0.25541435742159037,
        beta=-0.20308171,
        gamma=0.03468230656563422,
        delta=0.010559650431826953,
        epsilon=0.27560183,
    ),
}


class LogisticRandomVariable:
    """
    Minimal clone of contrib/vr-app/model/my-random-variable-stream.{h,cc}.
    """

    INFINITE_BOUND = 1e307

    def __init__(self, location: float, scale: float, bound: Optional[float] = None):
        self.location = location
        self.scale = scale
        self.bound = bound if bound is not None else self.INFINITE_BOUND

    def sample(self) -> float:
        while True:
            u = random.random()
            if u in (0.0, 1.0):
                continue
            candidate = self.location + self.scale * math.log(u / (1.0 - u))
            if abs(candidate - self.location) <= self.bound:
                return candidate

    def sample_int(self) -> int:
        return int(self.sample())


class VrBurstGenerator(BurstGenerator):
    """
    Replica of ns3::VrBurstGenerator.

    The burst size represents an encoded VR frame including the ns-3 header size;
    the period indicates when the next frame should be transmitted.
    """

    def __init__(
        self,
        app_name: VrAppName = VrAppName.VirusPopper,
        frame_rate: float = 60.0,
        target_data_rate_bps: float = 20e6,
    ):
        if frame_rate not in (30.0, 60.0):
            raise ValueError("Frame rate must be either 30 or 60 FPS")
        if target_data_rate_bps <= 0:
            raise ValueError("Target data rate must be positive")
        self._app = app_name
        self._frame_rate = frame_rate
        self._target_rate_bps = float(target_data_rate_bps)
        self._frame_rv: Optional[LogisticRandomVariable] = None
        self._period_rv: Optional[LogisticRandomVariable] = None
        self._setup_model()

    def _setup_model(self) -> None:
        coeffs = _VR_MODELS[self._app]
        target_mbps = self._target_rate_bps / 1e6
        frame_size_avg = self._target_rate_bps / 8.0 / self._frame_rate
        ifi_avg = 1.0 / self._frame_rate

        frame_dispersion = coeffs.alpha * math.pow(target_mbps, coeffs.beta)
        frame_scale = frame_size_avg * frame_dispersion
        self._frame_rv = LogisticRandomVariable(
            location=frame_size_avg, scale=frame_scale, bound=frame_size_avg
        )

        if self._frame_rate == 60.0:
            if coeffs.gamma is None:
                raise ValueError(f"Missing gamma coefficient for {self._app}")
            ifi_dispersion = coeffs.gamma
        else:
            if coeffs.delta is None or coeffs.epsilon is None:
                raise ValueError(f"Missing delta/epsilon coefficients for {self._app}")
            ifi_dispersion = coeffs.delta * math.pow(target_mbps, coeffs.epsilon)

        ifi_scale = ifi_avg * ifi_dispersion
        self._period_rv = LogisticRandomVariable(
            location=ifi_avg, scale=ifi_scale, bound=ifi_avg
        )

    def has_next_burst(self) -> bool:
        return True

    def generate_burst(self) -> Tuple[int, float]:
        assert self._frame_rv is not None and self._period_rv is not None
        burst_size = max(self._frame_rv.sample_int(), 24)
        period = max(self._period_rv.sample(), 0.0)
        return burst_size, period


def available_vr_apps() -> Iterable[str]:
    return [app.value for app in VrAppName]
