# Kimo — Voice-Controlled Robot Pet

Kimo is a four-wheeled robot pet that listens to spoken commands in English or Modern
Standard Arabic and drives itself accordingly. A host computer (a Raspberry Pi or laptop)
captures microphone audio, transcribes it, maps the transcription to a movement command, and
sends that command over USB serial to an Arduino that drives the motors through an L298N
driver. Kimo can also chase a colour: an OpenCV vision thread finds red objects in the camera
feed and steers toward them, scanning by rotating when the target is lost.

## How it works

The host-side pipeline is split into single-responsibility modules.

**Voice capture and transcription (`voice.py`)**
- Records from the microphone at 16 kHz with `sounddevice`, in 20 ms frames.
- Uses WebRTC VAD (aggressiveness level 3) to detect actual speech: recording starts after
  5 consecutive speech frames, stops after 25 silent frames, and is discarded unless at least
  1 second of speech was captured. Recording is capped at 8 seconds.
- Records a 1.5-second ambient noise profile at startup and subtracts it with `noisereduce`;
  clips whose denoised RMS is below the gate are dropped before any network call.
- Transcribes with Groq's hosted `whisper-large-v3-turbo`, biased by a prompt listing the
  expected command vocabulary in both languages. Results are discarded if the detected
  language is not English or Arabic, if Whisper's no-speech confidence is too high, or if the
  text matches a blacklist of known Whisper hallucinations.
- Falls back automatically to a local `faster-whisper` small model (int8 on CPU) whenever the
  cloud call fails or there is no internet.
- Offers a microphone picker at startup, including a phone microphone over DroidCam.

**Command interpretation (`brain.py`)**
- First pass is an instant keyword scan over bilingual keyword lists (English plus MSA, with
  Arabic diacritics stripped) mapping to `FORWARD`, `BACKWARD`, `LEFT`, `RIGHT`, `STOP` and
  `DANCE`, plus red-follow triggers such as "follow red" or "you are a bull".
- If no keyword matches and the sentence contains the word "think", the text is sent to a
  local Ollama instance running `phi3:mini` (temperature 0) which must answer with exactly one
  of the valid commands. Anything else returns `NOOP` so the robot ignores stray speech.

**Colour following (`vision.py`)**
- `ColorFollower` runs a background thread over an OpenCV capture at 320x240.
- Frames are converted to HSV and masked against two red hue ranges (red wraps around the hue
  circle), then cleaned with morphological opening and closing to remove noise and merge
  fragments.
- Contours below 1500 px are ignored; the remaining blobs give an area-weighted centroid,
  smoothed with an exponential moving average, and the horizontal position picks `LEFT`,
  `FORWARD` or `RIGHT` using a wide centre band (20%–80%) to prevent oscillation.
- When the target is lost the robot watches for 2 seconds, then rotates right in short bursts
  and looks again, repeating until it reappears.

**Motor link (`motor.py`)**
- `MotorController` opens the first available serial port from `/dev/ttyACM0` or
  `/dev/ttyUSB0` at 9600 baud, waits out the Arduino reset, and writes newline-terminated
  command strings.

**Firmware (`arduino/kimo/kimo.ino`)**
- Reads newline-terminated commands from serial and drives a 4WD chassis through an L298N:
  channel A for the left motors (`ENA` 9, `IN1` 2, `IN2` 3), channel B for the right motors
  (`ENB` 10, `IN3` 4, `IN4` 5), at PWM speed 200.
- Implements forward, backward, in-place left and right spins, stop, and a `DANCE` routine of
  full spins followed by rapid alternating turns.

**Entry point (`main.py`)**
- Runs two modes toggled with TAB. In VOICE mode the microphone loop drives the robot; in
  MANUAL mode a keyboard thread reads arrow keys for movement, Space for stop, D for dance,
  R to start red-following and ESC to stop it.
- Ctrl+C shuts the follower, the DroidCam process and the serial port down cleanly.

## Tech stack

- Python 3 on the host: sounddevice, webrtcvad, noisereduce, NumPy, groq, faster-whisper,
  OpenCV, pyserial, readchar, requests
- Ollama running `phi3:mini` locally for the optional reasoning fallback
- Arduino C++ firmware, L298N motor driver, 4WD chassis
- Optional DroidCam for using a phone as camera or microphone

## Project structure

```
Kimo Source Code/
├── main.py                # Entry point: voice/manual modes, keyboard thread
├── voice.py               # Mic capture, VAD, denoise, Groq + local Whisper transcription
├── brain.py               # Bilingual keyword matching and Ollama phi3:mini fallback
├── vision.py              # HSV colour detection and steering thread
├── motor.py               # Serial link to the Arduino
├── config.py              # Groq API key (not committed — see below)
├── arduino/
│   └── kimo/
│       └── kimo.ino       # Motor firmware for the L298N driver
├── .gitignore
└── README.md
```

## Getting started

### 1. Firmware

Open `arduino/kimo/kimo.ino` in the Arduino IDE, select your board, and upload it. The board
prints `KIMO READY` on the serial port at 9600 baud once it is running.

### 2. Host dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install sounddevice webrtcvad noisereduce numpy groq faster-whisper opencv-python pyserial readchar requests
```

On Debian or Raspberry Pi OS the audio stack also needs `sudo apt install portaudio19-dev`.

### 3. Configuration

`config.py` is intentionally excluded from version control because it holds an API key.
Create it locally with your own key from console.groq.com:

```python
# config.py
GROQ_API_KEY = "your-groq-api-key"
```

### 4. Optional local reasoning model

```bash
ollama pull phi3:mini
ollama serve
```

The brain expects Ollama at `http://localhost:11434`.

### 5. Run

```bash
python main.py
```

Pick a microphone when prompted, stay quiet during the 1.5-second noise calibration, then
speak a command or press TAB to drive manually.

## Author

Mohammad Salhab
