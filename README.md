# Boxapella

One-person multitrack video. Record yourself into one inset of a screen layout,
then record again into the next inset while the earlier takes play in your
headphones, and so on. All the insets play together as one master video, with
every voice mixed into one soundtrack.

Runs on Linux and Windows; see [WINDOWS.md](WINDOWS.md) for installing on Windows.

    boxapella [PROJECT_FOLDER]          the app
    boxapella new NAME [--template KEY] create a project under projects/
    boxapella templates                 list layout templates
    boxapella cameras                   list cameras ffmpeg can record from
    boxapella import PROJECT VIDEO [--slot ID]
    boxapella export PROJECT OUT.mp4 [--size 1920x1080|1280x720]
    boxapella calibrate                 measure audio latency (speakers, not headphones)

## Recording

1. **File → New project…**: give it a name and pick a template.
2. Click an inset, either on the picture or in the *Insets* table, and press **● Record** (R).
   The camera and microphone start, a count-in clicks in your headphones, and
   the other insets play in step, picture and sound, while you sing.
   Recording only ends when you press **■ Stop** (R). It carries on past the end
   of the other takes, so a take can be longer than anything recorded so far.
3. The take is saved as `takes/take-NNN.mp4` plus `take-NNN.wav`, and it is placed in the inset.
   The next empty inset is selected, ready for the next take.
4. **Export MP4…** renders the master video (1920 × 1080 or 1280 × 720, H.264 + AAC)
   into the project's `exports/` folder.

Wear headphones, so the earlier takes don't leak into the microphone.
For the first take, *Click track in the headphones while recording* gives you a
steady beat at the count-in tempo.

Recording into an inset that already has a take keeps the old take as an
alternate. Pick it again under *Take*. **File → Delete takes not in an inset…** cleans them up.
**Import video…** puts an existing video file into the selected inset instead
of recording.

### Insets table

| column | does |
|---|---|
| Take | which take this inset shows (or empty) |
| Voice | *As recorded*, any VocalFry preset, or *Custom (VocalFry editor)…* |
| ✎ | open VocalFry's editor on this inset's audio |
| dB | volume of this inset in the mix |
| Offset | slide the take later (+) or earlier (−) in ms, picture and sound together |
| Mute | leave this inset's audio out of the mix |
| Flip | mirror the picture left-right |

## Voices: VocalFry

Each inset's audio can be reshaped with VocalFry (`~/Claude/VocalFry`):

* **Preset**: choose one in the *Voice* column. VocalFry renders it in the
  background, and the reshaped voice is what you hear in playback, in the
  headphones while you record later takes, and in the export.
* **Custom**: choose *Custom (VocalFry editor)…* or press **✎**. VocalFry opens
  on that take, starting from the current preset or custom voice. Shape it with
  the sliders, then press **⮐ Send to Boxapella** (Ctrl+Enter) in VocalFry.
  Boxapella picks the new voice up within a second. You can keep adjusting and
  sending again.
* *As recorded* goes back to the original.

**Keeping the key:** a preset's pitch is usually not a whole number of octaves
from your singing, so as it stands it would put the voice out of tune with the
other takes. With *Settings → Timing & devices → VocalFry voices keep the key*
on (the default), the voice moves to whichever octave of your own pitch is
nearest the preset's. Intonation range, declination and vocal fry are held at
neutral too, because they bend notes off the key. The voice's character (vocal
tract, breathiness and the rest) is unchanged. VocalFry's editor opens with
*Keep key* ticked; untick it there for a deliberately off-key voice. Voices that
are already rendered keep their old pitch until you choose the preset again.

VocalFry's *Speaking rate* and *Pause length* would change the take's length
and break lip sync, so Boxapella always holds them at 100 %. *Send to
Boxapella* always renders the whole take, even if you trimmed it in VocalFry.
The reshaped audio is `voices/take-NNN.wav`, and a custom voice's settings are
saved beside it in `take-NNN.voice.json`. Long takes take a while to analyse,
and VocalFry's analysis uses a lot of memory for takes of several minutes.

## Templates

A template is a JSON file. The built-in ones are in `templates/`. Put your own in
`~/.config/boxapella/templates/` (**Settings → Open my templates folder**); a
file there with the same name as a built-in replaces it.

    {"boxapella": 1, "name": "TV inset (upper right)",
     "description": "A full-screen main picture with a television-style inset ...",
     "background": "#111116", "gap": 0, "border": {"width": 4, "color": "#ffffff"},
     "slots": [{"id": "1", "label": "Main",  "rect": [0, 0, 1, 1]},
               {"id": "2", "label": "Inset", "rect": [0.6, 0.07, 0.33, 0.33]}],
     "regions": []}

* `rect` = `[x, y, width, height]` as fractions of the screen (16:9). Later
  slots are drawn on top of earlier ones, so an inset can sit over a main picture.
* Each video fills its slot, with the overflow cropped from the centre.
* `gap` = pixels (at 1920 wide) between neighbouring slots. `border` (on the
  template or on a single slot) draws a frame around each slot.
* `regions` reserve part of the screen for something else:
  `{"id": "title", "kind": "text", "rect": [...], "text": "Title", "fill": "#1d1d28",
  "color": "#ffffff", "size": 0.06, "align": "center"}`. The text of each text
  region can be changed per project under *Template*. `"kind": "color"` is a plain fill.

Built-in templates: Full screen · Side by side · Fourths (2×2) · TV inset (upper
right) · Main + side panel · Main + lower third · Three across · Feature + two ·
Six (3×2) · Nine (3×3) · Main + four below · Title + fourths.

Switching template keeps each take in the slot with the same id. Takes whose slot
the new template doesn't have become alternates.

## Timing

Takes are lined up using the camera's own frame timestamps (same clock as the
computer's), the moment the microphone's first sample arrived, and the moment
the backing started. Two settings (**Settings → Timing & devices**) cover what
can't be measured directly:

* **Audio latency**: the time from the backing leaving the computer to your
  voice coming back through the microphone. **Calibrate…** measures it: take
  the headphones off, turn the speakers up, and it plays eight unevenly spaced clicks and listens
  for them. If a take still sounds early or late against the others, fix it with
  its *Offset* column.
* **Video offset**: a lip-sync nudge for new takes' pictures.

In this VirtualBox VM the round trip measured about 0.9 s (2026-11-01). Without
calibrating, each take lands that much later than the takes you sang along to.
Runs vary by about ±60 ms, so after calibrating a take may still need a small
*Offset* nudge by ear.

## Files

    projects/NAME/project.json      template, region texts, takes (slot, gain, offset, voice …)
    projects/NAME/takes/            take-NNN.mp4 (30 fps H.264 + AAC) and take-NNN.wav (48 kHz mono)
    projects/NAME/takes/proxy/      540p copies the app plays (decode at half the CPU cost); export uses the originals
    projects/NAME/voices/           VocalFry-reshaped audio per take
    projects/NAME/exports/          master videos
    ~/.config/boxapella/settings.json

`projects/` is git-ignored.

## Install

`./install.sh` creates `.venv`, which shares the system PyQt6 and numpy and adds
imageio-ffmpeg, whose bundled ffmpeg records from Video4Linux cameras. It also
installs the `boxapella` command in `~/.local/bin` and the desktop entry and icon.
`make_icon.py` redraws the icon: a golden rectangle cut into ever-smaller squares,
with the golden spiral running through them. Needs PipeWire (`pw-record`, `pw-play`).

Tests: `.venv/bin/python -m unittest test_core`

### Smooth playback

Each inset's decoder starts first and keeps a few frames buffered ahead; the
sound starts only once every inset is ready. Playback starts with 0.4 s of silence (so does the count-in when recording),
because a sound device waking from suspend can stutter for a moment. The video
in the insets comes from small 540p preview copies of each take, made when the
take is recorded or imported (older takes get theirs in the background when the
project opens). Their decoders run at low priority, so the sound gets the CPU
first. `pw-play` uses a 200 ms buffer.

### In VirtualBox

* Camera: **Devices → Webcams →** tick the camera. You have to do this again after
  each VM restart. VirtualBox's webcam passthrough delivered only about 6–7 frames
  per second from the HP 1080p camera, so takes look jerky even though they stay
  in sync. Passing the camera through as a USB device (**Devices → USB →** the
  camera; untick it under Webcams first) usually gives its full rate.
  `boxapella cameras --measure` reports the rate the camera really delivers, and
  Boxapella warns after any take recorded at under 15 fps.
* Microphone: the VM's sound card only hears anything if VirtualBox's audio
  input is on (**Devices → Audio → Audio Input**, or VM Settings → Audio →
  *Enable Audio Input*). Otherwise takes are silent.
