from __future__ import annotations


class EWMAModel:
    """EWMA per hour-bucket (0-23). O(1) per event; MVP uses hour-of-day only."""

    def __init__(self, alpha: float = 0.3):
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        self.alpha = alpha
        self._values: dict[int, float] = {}

    def update(self, bucket: int, count: int) -> float:
        prev = self._values.get(bucket, 0.0)
        value = self.alpha * float(count) + (1.0 - self.alpha) * prev
        self._values[bucket] = value
        return value

    def predict(self, bucket: int) -> float:
        return self._values.get(bucket, 0.0)

    def to_histogram(self) -> dict[int, float]:
        return dict(self._values)
