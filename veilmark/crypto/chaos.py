"""Chaotic keystream generators from the thesis.

The Mathematica version integrated each system with ``NDSolveValue`` (adaptive
step, PrecisionGoal 1) and thresholded the samples against their median to get
key bits. Adaptive integration is not bit-for-bit reproducible across machines,
so here every system is integrated with a *fixed-step* 4th-order Runge-Kutta
scheme in IEEE-754 float64 (numpy element-wise ops are deterministic), which
yields the exact same keystream on every Windows/Linux/macOS computer.

To make it fast enough for real files, ``lanes`` independent trajectories (each
with key-derived initial conditions) are integrated side by side, and every
state variable sample yields one key byte (taken from deep fractional digits,
which are the most sensitive to initial conditions).
"""

from __future__ import annotations

import numpy as np

LANES = 256
_BURN_IN = 1500  # steps discarded so trajectories decorrelate from their seeds


def _seed_offsets(seed: bytes, lanes: int, dims: int) -> np.ndarray:
    """Derive per-lane initial-condition perturbations in [0, 0.25) from key bytes."""
    import hashlib

    need = lanes * dims * 4
    stream = b""
    counter = 0
    while len(stream) < need:
        stream += hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        counter += 1
    words = np.frombuffer(stream[:need], dtype=">u4").astype(np.float64)
    return (words / 2**32 * 0.25).reshape(dims, lanes)


class _ChaoticStream:
    dims = 0
    step = 0.001
    base_ic = 0.5

    def __init__(self, seed: bytes, lanes: int = LANES):
        self.state = self.base_ic + _seed_offsets(seed, lanes, self.dims)
        self._buffer = np.empty(0, dtype=np.uint8)
        for _ in range(_BURN_IN):
            self._rk4()

    def derivative(self, s: np.ndarray) -> np.ndarray:  # pragma: no cover - abstract
        raise NotImplementedError

    def _rk4(self) -> None:
        h = self.step
        s = self.state
        k1 = self.derivative(s)
        k2 = self.derivative(s + (h / 2) * k1)
        k3 = self.derivative(s + (h / 2) * k2)
        k4 = self.derivative(s + h * k3)
        self.state = s + (h / 6) * (k1 + 2 * k2 + 2 * k3 + k4)

    def _sample(self) -> np.ndarray:
        # two integration steps per sample, then pull a byte out of the
        # fractional part (x * 1e4 mod 1) of every variable of every lane
        self._rk4()
        self._rk4()
        frac = np.mod(np.abs(self.state) * 10_000.0, 1.0)
        return np.floor(frac * 256.0).astype(np.uint8).ravel()

    def take(self, n: int) -> np.ndarray:
        chunks = [self._buffer]
        have = self._buffer.size
        while have < n:
            block = self._sample()
            chunks.append(block)
            have += block.size
        data = np.concatenate(chunks)
        self._buffer = data[n:]
        return data[:n]


class HyperChen4D(_ChaoticStream):
    """calSeqChen: 4-D hyperchaotic Chen system, a=35, b=3, c=12, gamma=7, d=0.49.

    x' = a(y - x) + u
    y' = gamma*x - x*z + c*y
    z' = x*y - b*z
    u' = z*y - d*u
    """

    dims = 4
    step = 0.002
    base_ic = 0.49  # thesis initial condition (0.49, 0.49, 0.49, 0.49)
    a, b, c, gamma, d = 35.0, 3.0, 12.0, 7.0, 0.49

    def derivative(self, s):
        x, y, z, u = s
        return np.stack(
            (
                self.a * (y - x) + u,
                self.gamma * x - x * z + self.c * y,
                x * y - self.b * z,
                z * y - self.d * u,
            )
        )


class Hyper5D(_ChaoticStream):
    """calc5D: 5-D hyperchaotic system with (30, 10, 15.7, 5, 2.5, 4.45, 38.5).

    x1' = a(x2 - x1) + x2*x3*x4
    x2' = b(x1 + x2) + x5 - x1*x3*x4
    x3' = -c*x2 - d*x3 - e*x4 + x1*x2*x4
    x4' = -f*x4 + x1*x2*x3
    x5' = -g(x1 + x2)
    """

    dims = 5
    step = 0.001
    base_ic = 0.6  # thesis initial condition (0.6, 0.6, 0.6, 0.6, 0.6)
    a, b, c, d, e, f, g = 30.0, 10.0, 15.7, 5.0, 2.5, 4.45, 38.5

    def derivative(self, s):
        x1, x2, x3, x4, x5 = s
        return np.stack(
            (
                self.a * (x2 - x1) + x2 * x3 * x4,
                self.b * (x1 + x2) + x5 - x1 * x3 * x4,
                -self.c * x2 - self.d * x3 - self.e * x4 + x1 * x2 * x4,
                -self.f * x4 + x1 * x2 * x3,
                -self.g * (x1 + x2),
            )
        )


class MersenneStream:
    """k2 / keyMT: Mersenne Twister keystream (numpy MT19937 raw output, stable across versions)."""

    def __init__(self, seed: bytes):
        self._bitgen = np.random.MT19937(int.from_bytes(seed, "big"))
        self._buffer = np.empty(0, dtype=np.uint8)

    def take(self, n: int) -> np.ndarray:
        if self._buffer.size < n:
            words = self._bitgen.random_raw((n - self._buffer.size) // 4 + 1).astype("<u4")
            self._buffer = np.concatenate((self._buffer, words.view(np.uint8)))
        out, self._buffer = self._buffer[:n], self._buffer[n:]
        return out
