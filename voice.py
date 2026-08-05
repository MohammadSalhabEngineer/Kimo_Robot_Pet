"""
voice.py — Microphone capture + speech-to-text for Kimo.

Transcription strategy:
  1. Groq cloud Whisper (whisper-large-v3-turbo) — fast, accurate, ~2s
  2. Local faster-whisper (small model) — fallback if Groq fails or no internet

Audio capture uses energy-based VAD via sounddevice.
"""

import io
import os
import wave
import subprocess
import numpy as np
import sounddevice as sd
import noisereduce as nr
import webrtcvad

from config import GROQ_API_KEY

# --- Microphone device selection ---
_mic_device_index: int | None = None   # None = system default
_droidcam_proc: subprocess.Popen | None = None

_DROIDCAM_IP   = "192.168.1.2"
_DROIDCAM_PORT = "4747"
_DROIDCAM_BIN  = os.path.join(os.path.dirname(__file__), "droidcam-cli")


def _build_mic_menu():
    """Return [(sounddevice_index, display_label)] for the two mic options."""
    devices = sd.query_devices()
    menu = []

    # Option 1 — webcam USB mic
    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0 and "Camera" in d["name"]:
            menu.append((i, "Webcam mic (USB)"))
            break

    # Option 2 — DroidCam (ALSA loopback capture side, hw:X,1)
    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0 and "Loopback" in d["name"] and "hw:3,1" in d["name"]:
            menu.append((i, "Phone mic (DroidCam)"))
            break

    # Fallback: any remaining input not already included
    included = {idx for idx, _ in menu}
    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0 and i not in included and "Loopback" not in d["name"]:
            menu.append((i, d["name"]))

    return menu


def _start_droidcam() -> None:
    global _droidcam_proc
    if _droidcam_proc and _droidcam_proc.poll() is None:
        return  # already running
    if not os.path.exists(_DROIDCAM_BIN):
        print("[Voice] droidcam-cli not found — phone mic unavailable.")
        return
    print(f"[Voice] Connecting to DroidCam at {_DROIDCAM_IP}:{_DROIDCAM_PORT}...")
    _droidcam_proc = subprocess.Popen(
        [_DROIDCAM_BIN, "-a", _DROIDCAM_IP, _DROIDCAM_PORT],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def stop_droidcam() -> None:
    global _droidcam_proc
    if _droidcam_proc and _droidcam_proc.poll() is None:
        _droidcam_proc.terminate()
        _droidcam_proc.wait(timeout=3)
    _droidcam_proc = None


def select_mic() -> None:
    global _mic_device_index
    menu = _build_mic_menu()

    if not menu:
        print("[Voice] No input devices found — using system default.")
        return

    print("\n[Voice] Available microphones:")
    for idx, (_, label) in enumerate(menu, start=1):
        print(f"  {idx}. {label}")
    print()

    while True:
        try:
            choice = input(f"Select mic [1-{len(menu)}] (Enter = default): ").strip()
            if choice == "":
                _mic_device_index = menu[0][0]
                print(f"[Voice] Using: {menu[0][1]}")
                break
            n = int(choice)
            if 1 <= n <= len(menu):
                _mic_device_index, label = menu[n - 1]
                print(f"[Voice] Selected: {label}")
                if label.startswith("Phone"):
                    _start_droidcam()
                break
            print(f"  Please enter a number between 1 and {len(menu)}.")
        except ValueError:
            print("  Invalid input.")


# --- Audio capture settings ---
SAMPLE_RATE       = 16000
FRAME_MS          = 20       # WebRTC VAD requires 10, 20 or 30ms frames
FRAME_SAMPLES     = int(SAMPLE_RATE * FRAME_MS / 1000)   # 320 samples
MAX_DURATION      = 8.0
SILENCE_THRESHOLD = 0.013    # post-denoise RMS gate (secondary filter)

# --- Noise reduction ---
_noise_profile: np.ndarray | None = None
_NOISE_CAL_SECS = 1.5   # seconds of silence to record at startup

def calibrate_noise() -> None:
    """Record ambient noise once at startup and build a subtraction profile."""
    global _noise_profile
    n_samples = int(SAMPLE_RATE * _NOISE_CAL_SECS)
    print(f"[Voice] Calibrating mic — stay quiet for {_NOISE_CAL_SECS}s...")
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                        dtype="float32", blocksize=n_samples,
                        device=_mic_device_index) as stream:
        block, _ = stream.read(n_samples)
    _noise_profile = block.flatten()
    print("[Voice] Noise calibration done.")

def _denoise(audio: np.ndarray) -> np.ndarray:
    """Subtract the ambient noise profile from captured audio."""
    if _noise_profile is None:
        return audio
    return nr.reduce_noise(y=audio, y_noise=_noise_profile,
                           sr=SAMPLE_RATE, stationary=True)


# --- Local Whisper fallback (lazy loaded) ---
_local_model = None

def _get_local_model():
    global _local_model
    if _local_model is None:
        from faster_whisper import WhisperModel
        print("[Voice] Loading local Whisper model (small)...")
        _local_model = WhisperModel("small", device="cpu", compute_type="int8")
        print("[Voice] Local model ready.")
    return _local_model


def _audio_to_wav_bytes(audio: np.ndarray) -> bytes:
    """Convert float32 numpy array to WAV bytes."""
    pcm = (audio * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


_NO_SPEECH_THRESHOLD = 0.10         # discard if Whisper thinks no speech

_HALLUCINATION_BLACKLIST = {
    "thank you", "thanks", "thank you.", "thanks.",
    "you", "so", "huh", "huh.", "okay", "ok",
    "lifecycleíficquelsquels",
    "ترجمة نانسي قنقر", "ترجمة نانسي", "نانسي قنقر",
}
_ALLOWED_LANGUAGES   = {"en", "ar", "english", "arabic"}  # codes + full names

def _transcribe_groq(audio: np.ndarray) -> str:
    """Send audio to Groq Whisper API. Returns transcribed text or raises."""
    from groq import Groq
    client = Groq(api_key=GROQ_API_KEY)
    wav_bytes = _audio_to_wav_bytes(audio)
    transcription = client.audio.transcriptions.create(
        model="whisper-large-v3-turbo",
        file=("audio.wav", wav_bytes, "audio/wav"),
        response_format="verbose_json",
        prompt="Kimo forward backward left right stop dance follow red. تقدم للأمام تراجع يسار يمين توقف ارقص اتبع الأحمر أنت ثور",
    )
    # Discard if detected language is not English or Arabic
    detected_lang = getattr(transcription, "language", "en")
    if detected_lang.lower() not in _ALLOWED_LANGUAGES:
        print(f"[Voice] Discarded — detected language: {detected_lang}")
        return ""
    # Discard if Whisper isn't confident real speech exists
    if transcription.segments:
        avg_no_speech = sum(s.get("no_speech_prob", 0) if isinstance(s, dict) else s.no_speech_prob for s in transcription.segments) / len(transcription.segments)
        if avg_no_speech > _NO_SPEECH_THRESHOLD:
            print(f"[Voice] Discarded — no speech confidence: {avg_no_speech:.2f}")
            return ""
    print(f"[Voice] Detected language: {detected_lang}")
    return transcription.text.strip()


def _transcribe_local(audio: np.ndarray) -> str:
    """Transcribe using local faster-whisper small model."""
    model = _get_local_model()
    segments, _ = model.transcribe(audio, language="en", beam_size=1)
    return " ".join(seg.text for seg in segments).strip()


def _capture_audio() -> np.ndarray | None:
    """
    Record from mic using WebRTC VAD (Google's speech detector).
    Only triggers on actual human speech, not background noise.
    Returns float32 numpy array or None if nothing was captured.
    """
    vad = webrtcvad.Vad(3)   # aggressiveness 3 = most aggressive noise filtering

    # Thresholds (in 20ms frames)
    SPEECH_TRIGGER    = 5    # consecutive speech frames needed to start recording (= 0.1s)
    SILENCE_STOP      = 25   # consecutive non-speech frames to end recording (= 0.5s)
    MIN_SPEECH_FRAMES = 50   # minimum speech frames to consider valid (= 1.0s)
    max_frames       = int(MAX_DURATION * 1000 / FRAME_MS)

    frames        = []
    speech_frames = []
    speech_count  = 0
    silence_count = 0
    triggered     = False

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                        dtype="int16", blocksize=FRAME_SAMPLES,
                        device=_mic_device_index) as stream:
        for _ in range(max_frames):
            block, _ = stream.read(FRAME_SAMPLES)
            pcm_bytes = block.tobytes()
            is_speech = vad.is_speech(pcm_bytes, SAMPLE_RATE)

            if not triggered:
                if is_speech:
                    speech_count += 1
                    frames.append(block.copy())
                    if speech_count >= SPEECH_TRIGGER:
                        triggered = True
                        silence_count = 0
                else:
                    speech_count = max(0, speech_count - 1)
                    frames = frames[-SPEECH_TRIGGER:]   # keep pre-roll buffer
            else:
                frames.append(block.copy())
                if is_speech:
                    silence_count = 0
                    speech_frames.append(block.copy())
                else:
                    silence_count += 1
                    if silence_count >= SILENCE_STOP:
                        break

    if len(speech_frames) < MIN_SPEECH_FRAMES:
        return None

    audio_int16 = np.concatenate(frames, axis=0).flatten()
    return audio_int16.astype(np.float32) / 32768.0


def _is_valid_text(text: str) -> bool:
    """Returns True if text contains at least one real alphabetic word."""
    words = [w for w in text.split() if any(c.isalpha() for c in w)]
    return len(words) >= 1


def listen_and_transcribe() -> str:
    """
    Capture voice command and return transcribed text.
    Uses Groq cloud first, falls back to local Whisper automatically.
    Returns empty string if nothing was heard.
    """
    if _noise_profile is None:
        calibrate_noise()

    print("[Voice] Listening...")
    audio = _capture_audio()

    if audio is None:
        return ""

    audio = _denoise(audio)

    # If denoised audio is near-silent, it was all noise — skip Groq entirely
    denoised_rms = float(np.sqrt(np.mean(audio ** 2)))
    print(f"[Voice] Denoised RMS: {denoised_rms:.4f}")
    if denoised_rms < SILENCE_THRESHOLD:
        return ""

    # --- Try Groq first ---
    try:
        text = _transcribe_groq(audio)
        if not _is_valid_text(text):
            return ""
        print("[Voice] Groq transcription OK")
        return text
    except Exception as e:
        print(f"[Voice] Groq failed ({e}) — falling back to local Whisper...")

    # --- Local fallback ---
    try:
        return _transcribe_local(audio)
    except Exception as e:
        print(f"[Voice] Local Whisper error: {e}")
        return ""
