# Boxapella on macOS

The same code runs on macOS, Windows and Linux. Boxapella needs **Python 3.10 or newer**
(macOS's own `python3` is too old):

    brew install python@3.13        # Homebrew: https://brew.sh
    # or the installer from https://www.python.org/downloads/macos/

Then, in Terminal:

    git clone https://github.com/zklaas/boxapella.git Boxapella
    cd Boxapella
    bash install-macos.sh

That creates `.venv` (PyQt6, numpy, sounddevice, imageio-ffmpeg), a `boxapella` command in `~/.local/bin`, and a
**Boxapella** app in your Applications folder (Launchpad, Spotlight, the Dock).

macOS asks for **camera** and **microphone** permission the first time Boxapella records: allow both (System Settings > Privacy & Security, if you missed the question). Cameras are found through AVFoundation and recorded at 1280x720. Audio goes through PortAudio (the sounddevice package), as on Windows: choose the microphone in Settings > Timing & devices, by part of its name (`boxapella devices` lists them). To play MIDI backing tracks, install FluidSynth (`brew install fluid-synth`) and put a General MIDI SoundFont (.sf2) in `~/Library/Audio/Sounds/Banks`. VocalFry voices work when VocalFry is installed the same way (`vocalfry` command) or sits in a `VocalFry` folder next to this one.

To remove it: delete the folder, `~/Applications/Boxapella.app` and `~/.local/bin/boxapella`.

macOS support has not yet been tested on a Mac; please report anything that does
not work.
