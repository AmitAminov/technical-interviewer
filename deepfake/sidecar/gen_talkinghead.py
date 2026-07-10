"""Generate a lip-synced talking-head video from a character image + text.

text -> Kokoro TTS (the existing HeadTTS sidecar on :8012) -> wav
image + wav -> lipsync (Wav2Lip) -> mp4

Usage: python gen_talkinghead.py <image> "<text>" <out.mp4> [voice]
"""
import base64
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
# Make bundled ffmpeg discoverable.
os.environ["PATH"] = os.path.join(HERE, "..", "bin") + os.pathsep + os.environ.get("PATH", "")

VOICE_URL = os.environ.get("TI_VOICE_URL", "http://127.0.0.1:8012")


def synth_wav(text, out_wav, voice="af_bella", speed=1.0):
    body = json.dumps({"input": text, "voice": voice, "language": "en-us",
                       "speed": speed, "audioEncoding": "wav"}).encode()
    req = urllib.request.Request(f"{VOICE_URL}/v1/synthesize", data=body,
                                 headers={"Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=180))
    raw = base64.b64decode(d["audio"])
    open(out_wav, "wb").write(raw)
    return len(raw)


def main():
    image, text, out = sys.argv[1], sys.argv[2], sys.argv[3]
    voice = sys.argv[4] if len(sys.argv) > 4 else "af_bella"
    wav = os.path.join(HERE, "cache_line.wav")

    t0 = time.perf_counter()
    n = synth_wav(text, wav, voice)
    t_tts = time.perf_counter() - t0
    print(f"TTS: {n} bytes wav in {t_tts:.2f}s")

    from lipsync import LipSync
    import torch
    print("cuda:", torch.cuda.is_available(),
          torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")

    lip = LipSync(
        model="wav2lip",
        checkpoint_path=os.path.join(HERE, "weights", "wav2lip_gan_ls.pth"),
        nosmooth=True,
        device="cuda" if torch.cuda.is_available() else "cpu",
        cache_dir=os.path.join(HERE, "cache"),
        img_size=96,
        save_cache=True,
    )
    t1 = time.perf_counter()
    lip.sync(image, wav, out)
    t_lip = time.perf_counter() - t1
    print(f"LIPSYNC: {out} in {t_lip:.2f}s  (total {t_tts + t_lip:.2f}s)")


if __name__ == "__main__":
    main()
