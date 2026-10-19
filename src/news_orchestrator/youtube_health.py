"""Track transport progress and the media clock without contacting YouTube APIs."""

from collections import deque
import time


class ProgressClock:
    def __init__(self, tick=None):
        self.started = time.monotonic() if tick is None else tick
        self.last_advance = self.started
        self.last_bytes_advance = self.started
        self.position = None
        self.sent_bytes = None
        self.first = None
        self.samples = deque()
        self.slow_since = None
        self.late_since = None
        self.rewound = False

    def observe(self, position_us, sent_bytes=None, tick=None):
        tick = time.monotonic() if tick is None else tick
        advanced = False
        if isinstance(position_us, int) and position_us >= 0:
            position = position_us / 1_000_000
            if self.position is not None and position < self.position - 1:
                self.rewound = True
            if self.position is None or position > self.position:
                self.last_advance = tick
                advanced = True
            self.position = position
            if self.first is None:
                self.first = (tick, position)
            self.samples.append((tick, position))
            while len(self.samples) > 1 and tick - self.samples[1][0] >= 60:
                self.samples.popleft()
        if isinstance(sent_bytes, int) and sent_bytes >= 0:
            if self.sent_bytes is None or sent_bytes > self.sent_bytes:
                self.last_bytes_advance = tick
            self.sent_bytes = sent_bytes
        metrics = self.metrics(tick)
        slow = metrics["media_rate"] is not None and metrics["media_rate"] < 0.85
        late = metrics["lag_seconds"] is not None and metrics["lag_seconds"] > 20
        self.slow_since = (tick if self.slow_since is None else self.slow_since) if slow else None
        self.late_since = (tick if self.late_since is None else self.late_since) if late else None
        return advanced

    def metrics(self, tick=None):
        tick = time.monotonic() if tick is None else tick
        rate = None
        if self.samples and tick - self.samples[0][0] >= 30:
            elapsed = tick - self.samples[0][0]
            rate = max(0, (self.position - self.samples[0][1]) / elapsed)
        lag = None if self.first is None else max(0, tick - self.first[0] - (self.position - self.first[1]))
        return {"media_rate": round(rate, 3) if rate is not None else None,
                "lag_seconds": round(lag, 2) if lag is not None else None}

    def problem(self, tick=None):
        tick = time.monotonic() if tick is None else tick
        if self.rewound:
            return "El reloj de salida retrocedió; reconectando para recuperar una línea temporal continua."
        if tick - self.last_advance > 45:
            return "La salida no ha avanzado durante 45 segundos; reconectando con YouTube."
        if self.sent_bytes is not None and tick - self.last_bytes_advance > 45:
            return "La conexión no ha enviado datos durante 45 segundos; reconectando con YouTube."
        if self.slow_since is not None and tick - self.slow_since >= 20:
            return "La salida avanza por debajo de la velocidad de directo; reconectando para recuperar el ritmo."
        if self.late_since is not None and tick - self.late_since >= 20:
            return "La salida acumula más de 20 segundos de retraso; reconectando para recuperar el directo."
        return ""
