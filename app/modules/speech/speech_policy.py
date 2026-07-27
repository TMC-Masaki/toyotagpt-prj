import time

class SpeechPolicy:
  def __init__(self):
    self.last_spoken = 0.0

  def should_speak(self, enabled: bool, min_interval_sec: float, risk_score: float) -> bool:
    if not enabled:
      return False
    now = time.time()
    if (now - self.last_spoken) < min_interval_sec and risk_score < 0.8:
      return False
    self.last_spoken = now
    return True
