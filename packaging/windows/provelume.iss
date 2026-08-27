#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef MyStageDir
  #error MyStageDir is required
#endif
#ifndef MyOutputDir
  #error MyOutputDir is required
#endif

[Setup]
AppId={{E41A426B-F5FC-473F-A096-875017656A31}
AppName=Provelume
AppVersion={#MyAppVersion}
AppVerName=Provelume {#MyAppVersion} Preview
AppPublisher=Neobeta
AppPublisherURL=https://provelume.com
AppSupportURL=https://github.com/gabned/provelume/issues
AppUpdatesURL=https://github.com/gabned/provelume/releases
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany=Neobeta
VersionInfoDescription=Provelume Windows Preview Installer
VersionInfoProductName=Provelume
DefaultDirName={localappdata}\Programs\Provelume
DefaultGroupName=Provelume
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19045
OutputDir={#MyOutputDir}
OutputBaseFilename=Provelume-Setup-{#MyAppVersion}-x64
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
SetupLogging=yes
AppMutex=Local\ProvelumeDesktop
UninstallDisplayIcon={app}\Provelume.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Files]
Source: "{#MyStageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Provelume"; Filename: "{app}\Provelume.exe"
Name: "{autodesktop}\Provelume"; Filename: "{app}\Provelume.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
Filename: "{app}\Provelume.exe"; Description: "{cm:LaunchProgram,Provelume}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Runtime files live under {app}. Launcher state and Instance data intentionally live elsewhere
; and are not deleted by uninstall.
