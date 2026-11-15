# Boxapella on macOS

The same code runs on macOS, Windows and Linux.

## Where to type the commands

Everything below is typed into **Terminal**: open Applications > Utilities >
Terminal, or press ⌘-Space, type *Terminal* and press Return. Press Return after
each line.

## 1. Install Python

Boxapella needs **Python 3.10 or newer** (the `python3` that comes with macOS is
too old). The simplest way is the installer from
https://www.python.org/downloads/macos/ ; or, with Homebrew (https://brew.sh):

    brew install python@3.13

## 2. Get Boxapella

**With git:**

    git clone https://github.com/zklaas/boxapella.git Boxapella
    cd Boxapella

(The first time, macOS offers to install its command-line tools for `git`: accept,
then run the line again.)

**Without git:** on https://github.com/zklaas/boxapella click **Code > Download ZIP**;
the Mac unpacks it into your Downloads folder (`boxapella-main`). In Terminal type
`cd ` (with a space), drag that folder onto the Terminal window, and press Return.

## 3. Install it

    bash install-macos.sh

That creates `.venv` (PyQt6, numpy, sounddevice, imageio-ffmpeg), a `boxapella` command in `~/.local/bin`, and a
**Boxapella** app in your Applications folder: start it from Launchpad, Spotlight or
the Dock from then on.

macOS asks for **camera** and **microphone** permission the first time Boxapella records: allow both (System Settings > Privacy & Security, if you missed the question). Cameras are found through AVFoundation and recorded at 1280x720. Audio goes through PortAudio (the sounddevice package), as on Windows: choose the microphone in Settings > Timing & devices, by part of its name (`boxapella devices` lists them). To play MIDI backing tracks, install FluidSynth (`brew install fluid-synth`) and put a General MIDI SoundFont (.sf2) in `~/Library/Audio/Sounds/Banks`. VocalFry voices work when VocalFry is installed the same way (`vocalfry` command) or sits in a `VocalFry` folder next to this one.

To remove it: delete the folder, `~/Applications/Boxapella.app` and `~/.local/bin/boxapella`.

If something doesn't work, please write to zklaastest-testing@yahoo.com.
