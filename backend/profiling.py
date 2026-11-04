"""Monotonic, per-bundle timings; independent of camera/edge wall clocks."""
from time import perf_counter


class StageTimer:
    def __init__(self):
        self.started = self.previous = perf_counter()
        self.stages = {}

    def mark(self, stage: str):
        now = perf_counter()
        self.stages[stage] = (now - self.previous) * 1000
        self.previous = now

    def result(self):
        return {**self.stages, "total_ms": (perf_counter() - self.started) * 1000}
