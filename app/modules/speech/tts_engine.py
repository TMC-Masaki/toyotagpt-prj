import subprocess

def speak_jp(text: str) -> None:
  # espeak-ng は日本語音声が機械的でもMVPには十分
  # -v ja: 日本語, -s: speed
  subprocess.run(["espeak-ng", "-v", "ja", "-s", "165", text], check=False)
