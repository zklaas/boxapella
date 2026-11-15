# Installing Boxapella

## Linux

```
git clone https://github.com/zklaas/boxapella.git
cd boxapella
python3 -m pip install --user PyQt6 imageio-ffmpeg numpy sounddevice   # or your distribution's packages
./install.sh
```

## Windows

```
git clone https://github.com/zklaas/boxapella.git
cd boxapella
py -m pip install PyQt6 imageio-ffmpeg numpy sounddevice
powershell -ExecutionPolicy Bypass -File install.ps1
```

## macOS (untested)

```
git clone https://github.com/zklaas/boxapella.git
cd boxapella
python3 -m pip install --user PyQt6 imageio-ffmpeg numpy sounddevice
python3 boxapella.py
```
