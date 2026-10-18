"""95% Wilson score interval for a binomial pass rate (Requirement 10.2).

With p = passes / n and z = 1.959964:

    center = (p + z^2 / (2n)) / (1 + z^2 / n)
    half   = z * sqrt(p (1 - p) / n + z^2 / (4 n^2)) / (1 + z^2 / n)
    [low, high] = [center - half, center + half]

It is used instead of the normal approximation because it stays inside [0, 1] and behaves well near
0 and 1 at n = 30. For reference, 27/30 gives [0.744, 0.965] and 15/30 gives [0.332, 0.668].
"""

from __future__ import annotations

import math

Z95 = 1.959964


def wilson_interval(passes: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    if not 0 <= passes <= n:
        raise ValueError(f"passes must be in [0, {n}], got {passes}")
    p = passes / n
    z2 = z * z
    denominator = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denominator
    # The exact interval satisfies 0 <= low <= p <= high <= 1; clamp only last-bit rounding at p = 0 or 1.
    low = min(max(0.0, center - half), p)
    high = max(min(1.0, center + half), p)
    return low, high
