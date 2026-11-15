; Inno Setup script: the Windows installer for Boxapella.
; Built by .github/workflows/release.yml from PyInstaller's dist\Boxapella folder:
;   iscc /DAppVersion=1.0.0 packaging\boxapella.iss
; Installs for the current user only (no administrator rights), adds a Start-menu
; entry and an uninstaller (Settings > Apps).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{E5C77A81-838D-520E-9C1B-9087EF3130A2}
AppName=Boxapella
AppVersion={#AppVersion}
AppPublisher=Zachary Klaas
AppPublisherURL=https://github.com/zklaas/boxapella
DefaultDirName={localappdata}\Programs\Boxapella
DefaultGroupName=Boxapella
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=Boxapella-Setup-Windows
SetupIconFile=..\icons\boxapella.ico
UninstallDisplayIcon={app}\Boxapella.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\Boxapella\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Boxapella"; Filename: "{app}\Boxapella.exe"
Name: "{userdesktop}\Boxapella"; Filename: "{app}\Boxapella.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\Boxapella.exe"; Description: "Start Boxapella"; Flags: nowait postinstall skipifsilent
