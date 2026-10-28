# VoiceLab

Tune Piper voices and keep a catalog of presets any robot can use.

## Files

    VoiceLab/
      tuner.py        the app you open
      voicelab.py     the engine robots import
      catalog.json    your saved presets
      voices/         Piper voice files

## Setup (Windows)

    cd C:\Users\Yeyian\Development\VoiceLab
    python -m venv .venv
    .\.venv\Scripts\activate
    pip install -r requirements.txt
    python tuner.py

Voice files (.onnx and .onnx.json) go in `voices/`. Use the Download box in the
tuner, or copy them in. Browse and hear voices at https://rhasspy.github.io/piper-samples

## Sliders

- Speed: how fast he talks
- Pitch: semitones up or down, speed stays the same
- Expressiveness: how much emotion and variation (Piper noise_scale)
- Rhythm wobble: how uneven the timing is (Piper noise_w_scale)
- Robot effect / Robot tone: ring mod mix and its carrier frequency
- Volume

## Using a preset in a robot

From the robot's venv:

    pip install -e C:\Users\Yeyian\Development\VoiceLab

Then in code:

    from voicelab import speak
    speak("stelly", "Hi Skyler!")

Or get the audio without playing it:

    from voicelab import get_preset, render
    audio, sr = render(get_preset("stelly"), "Hi Skyler!")

On the Pi, clone this repo too and copy the voices folder over (voice files are
gitignored because they are big):

    scp -r voices <pi-user>@<pi-tailscale-name>:~/VoiceLab/
