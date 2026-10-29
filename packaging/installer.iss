; Inno Setup script: per-user install (no admin rights), Turkish wizard.
;   iscc /DAppVersion=1.1.0 packaging\installer.iss
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif

[Setup]
AppId={{6C3B2E4A-6F0E-4C6B-9E1A-7A5B1D2C9F10}
AppName=TraderBot
AppVersion={#AppVersion}
AppPublisher=TraderBot
DefaultDirName={localappdata}\Programs\TraderBot
DefaultGroupName=TraderBot
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=TraderBot-Setup-{#AppVersion}
SetupIconFile=traderbot.ico
UninstallDisplayIcon={app}\TraderBot.exe
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\TraderBot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\TraderBot"; Filename: "{app}\TraderBot.exe"
Name: "{autodesktop}\TraderBot"; Filename: "{app}\TraderBot.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\TraderBot.exe"; Description: "{cm:LaunchProgram,TraderBot}"; Flags: nowait postinstall skipifsilent
