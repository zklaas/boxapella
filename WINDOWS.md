# Boxapella on Windows

The same code runs on Windows and Linux. Install with PowerShell:

    git clone https://github.com/zklaas/boxapella.git
    cd boxapella
    powershell -ExecutionPolicy Bypass -File install.ps1

That creates `.venv` (PyQt6, numpy, imageio-ffmpeg, sounddevice), a `boxapella`
command on your PATH (open a new terminal first), and a **Boxapella** Start-menu entry.
Python 3.10 or newer is needed. If you also want VocalFry voices, install Python
**3.13** (`winget install --id Python.Python.3.13 -e --scope user`), because
VocalFry's pyworld has no Windows build for 3.14 yet.

Check it:

    boxapella devices                    # cameras (DirectShow) and audio devices
    boxapella cameras --measure          # the frame rate the camera really delivers
    .venv\Scripts\python -m unittest test_core

## What's different from Linux

| | Linux | Windows |
|---|---|---|
| camera | Video4Linux (`/dev/video0`), kernel timestamps | DirectShow (`video=Camera name`), wall-clock timestamps |
| sound | pw-record + pw-play (two programs, clocks matched by timing) | one full-duplex PortAudio stream: the backing's start is known to the sample |
| settings | `~/.config/boxapella/` | `%APPDATA%\Boxapella\` |
| VocalFry | `vocalfry` on PATH or `~/Claude/VocalFry` | `vocalfry` on PATH, or a `VocalFry` folder beside the `boxapella` folder |

Because playback and recording share one clock on Windows, takes should line up
more consistently than in the Linux VM. Still run **Settings → Timing & devices
→ Calibrate…** once, with the headphones off and the speakers on. The latency
measured in the Linux VM (about 0.9 s) doesn't apply here, so recalibrate. The
setting is stored separately on each computer.

**Microphone:** blank = Windows' default input. To pick another, type part of its
name as listed by `boxapella devices` (for example `Realtek`) into Settings →
Timing & devices → Microphone.

Projects live in the `projects\` folder inside the app folder, as on Linux.
