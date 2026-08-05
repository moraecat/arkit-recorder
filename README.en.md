# ARKit Recorder

[한국어](README.md) | **English** | [日本語](README.ja.md)

<img width="1440" height="1440" alt="arkit-recorder" src="https://github.com/user-attachments/assets/68c2aec8-ee43-4c9c-83ed-8b188bcdcda6" />

An always-on UDP proxy that **records the raw iPhone face tracking signal
(iFacialMocap) and replays it — no iPhone required**.

It captures iFacialMocap protocol packets verbatim and re-sends them with their
original timing, so it is not tied to any specific software — **playback works
with any tool that receives the iFacialMocap protocol**
([Warudo](https://warudo.app), VSeeFace, VNyan, the iFacialMocap PC software,
and so on). Built for AFK loops and repeatable facial performances during
streams.

## How it works

```
[Passthrough / Record]
iPhone app --UDP--> ARKit Recorder :49983 --forwarded as-is--> receiver :49984
                        |
                        +--> (while recording) lossless log to clips/name.jsonl

[Playback / Scrub]
clip --> ARKit Recorder --original timing--> receiver :49984
         (live packets are blocked meanwhile; crossfades back on finish)
```

The iFacialMocap receiver side is plain UDP — it cannot tell whether packets
come from the iPhone or from this program. Packets are stored without any
parsing or transformation, so playback fidelity is 100%: all 52 ARKit
blendshapes, head position/rotation, and eye gaze are preserved.

## Features

- **Passthrough**: a transparent proxy (iPhone → receiver) when idle
- **Recording**: stops the moment you press the button, lossless JSONL,
  real-time activity waveform
- **Playback**: trim-range playback/looping, live range editing during
  playback, start/loop/return crossfades
- **Timeline**: activity and per-blendshape (52) curves, scrubbing (the avatar
  follows your drag in real time), non-destructive trimming
- **Pause**: click/release on the timeline freezes that frame (keepalive
  prevents receiver timeout), shown as a toggle button
- **Clip management**: rename/delete/duration display, settings GUI
  (ports and crossfades applied immediately)

## Usage

### One-time setup

Change your receiver's iFacialMocap listen port from **49983 to 49984**
(e.g. the Port property of Warudo's iFacialMocap Receiver asset). Leave your
iPhone app settings (PC IP) unchanged. If your receiver's port cannot be
changed, you can instead adjust this program's forward port in its settings
(anything other than the listen port 49983 works).

### Run

Run the distributed `arkit-recorder.exe`, or:

```
pip install -r requirements.txt
python main.py
```

On first launch, `config.json` and a `clips/` folder are created next to the
exe (or main.py). Tracking does not reach the receiver while this program is
closed, so keep it running during streams.

## Requirements

- A Windows PC (the exe is standalone — nothing to install)
- An iPhone with ARKit face tracking + an app that sends the iFacialMocap
  protocol (iFacialMocap, FaceMotion3D, ...)
- A receiver that accepts the iFacialMocap protocol (Warudo, VSeeFace,
  VNyan, ...)

## Development (running from source)

Requires Python 3.11+ and PySide6 (`pip install -r requirements.txt`).
The core logic uses only the standard library; tests run without PySide6.

```
python -m pytest tests/ -v        # tests (92)
pyinstaller --onefile --windowed --name arkit-recorder main.py   # build exe
```

## License

[MIT](LICENSE)
