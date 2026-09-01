#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef MyStageDir
  #error MyStageDir is required
#endif
#ifndef MyOutputDir
  #error MyOutputDir is required
#endif
#ifndef MyIconFile
  #error MyIconFile is required
#endif

[Setup]
AppId={{E41A426B-F5FC-473F-A096-875017656A31}
AppName=Provelume
AppVersion={#MyAppVersion}
AppVerName=Provelume {#MyAppVersion} Preview
AppPublisher=Neobeta
; AppPublisher is descriptive Add/Remove Programs metadata. It is not an Authenticode claim.
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
UninstallDisplayName=Provelume {#MyAppVersion} Preview
SetupIconFile={#MyIconFile}
SignedUninstaller=no
ChangesAssociations=no
ChangesEnvironment=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Files]
Source: "{#MyStageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Provelume"; Filename: "{app}\Provelume.exe"; IconFilename: "{app}\Provelume.exe"; AppUserModelID: "Provelume.Desktop"
Name: "{autodesktop}\Provelume"; Filename: "{app}\Provelume.exe"; IconFilename: "{app}\Provelume.exe"; AppUserModelID: "Provelume.Desktop"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "traydefault"; Description: "{cm:TrayDefaultTask}"; GroupDescription: "{cm:ShellPreferences}"
Name: "loginstartup"; Description: "{cm:LoginStartupTask}"; GroupDescription: "{cm:ShellPreferences}"; Flags: unchecked

[Run]
Filename: "{app}\Provelume.exe"; Description: "{cm:LaunchProgram,Provelume}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\Provelume.exe"; Parameters: "--remove-login-startup"; Flags: runhidden waituntilterminated skipifdoesntexist

[UninstallDelete]
; Runtime files live under {app}. Launcher state and Instance data intentionally live elsewhere
; and are not deleted by uninstall.

[CustomMessages]
english.ShellPreferences=Shell preferences
italian.ShellPreferences=Preferenze shell
english.TrayDefaultTask=Keep Provelume running in the system tray by default
italian.TrayDefaultTask=Mantieni Provelume nell'area di notifica per impostazione predefinita
english.LoginStartupTask=Start Provelume when I sign in to Windows (separate opt-in)
italian.LoginStartupTask=Avvia Provelume all'accesso a Windows (scelta separata)
english.PortPageTitle=Local endpoint
italian.PortPageTitle=Endpoint locale
english.PortPageDescription=Choose an explicit loopback port
italian.PortPageDescription=Scegli una porta loopback esplicita
english.PortPrompt=Port (1024-65535; default 44851):
italian.PortPrompt=Porta (1024-65535; predefinita 44851):
english.PortInvalid=Enter an integer from 1024 through 65535. Ports 1-1023 are reserved.
italian.PortInvalid=Inserisci un intero da 1024 a 65535. Le porte 1-1023 sono riservate.
english.EndpointUnavailable=The selected loopback port is occupied or the shell settings could not be applied. Setup will roll back; no random port was selected.
italian.EndpointUnavailable=La porta loopback scelta è occupata o non è stato possibile applicare le impostazioni shell. L'installazione verrà ripristinata; non è stata scelta una porta casuale.
english.EndpointPreflightUnavailable=The selected loopback port is occupied or could not be validated. Setup will stop before copying files; no random port was selected.
italian.EndpointPreflightUnavailable=La porta loopback scelta è occupata o non è stato possibile validarla. L'installazione si fermerà prima di copiare file; non è stata scelta una porta casuale.

[Code]
var
  PortPage: TInputQueryWizardPage;
  ExistingShellSettings: Boolean;

procedure InitializeWizard;
begin
  ExistingShellSettings := FileExists(
    ExpandConstant('{localappdata}\Provelume\launcher.json'));
  PortPage := CreateInputQueryPage(
    wpSelectTasks,
    ExpandConstant('{cm:PortPageTitle}'),
    ExpandConstant('{cm:PortPageDescription}'),
    ExpandConstant('{cm:PortPrompt}'));
  PortPage.Add(ExpandConstant('{cm:PortPrompt}'), False);
  PortPage.Values[0] := ExpandConstant('{param:LOCALPORT|44851}');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := ExistingShellSettings and (PageID = PortPage.ID);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  SelectedPort: Integer;
begin
  Result := True;
  if CurPageID = PortPage.ID then
  begin
    SelectedPort := StrToIntDef(PortPage.Values[0], -1);
    if (SelectedPort < 1024) or (SelectedPort > 65535) then
    begin
      MsgBox(ExpandConstant('{cm:PortInvalid}'), mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
  PowerShell: String;
  ProbeCommand: String;
  SelectedPort: Integer;
begin
  NeedsRestart := False;
  Result := '';
  if ExistingShellSettings then
    exit;
  SelectedPort := StrToIntDef(PortPage.Values[0], -1);
  if (SelectedPort < 1024) or (SelectedPort > 65535) then
  begin
    Result := ExpandConstant('{cm:PortInvalid}');
    exit;
  end;
  PowerShell := ExpandConstant(
    '{sys}\WindowsPowerShell\v1.0\powershell.exe');
  { The parsed integer's decimal form is the only dynamic command value. }
  { Host, path and unvalidated wizard text cannot reach this socket probe. }
  ProbeCommand :=
    '-NoLogo -NoProfile -NonInteractive -Command "' +
    '$socket=$null;$code=1;try{' +
    '$socket=[Net.Sockets.Socket]::new(' +
    '[Net.Sockets.AddressFamily]::InterNetwork,' +
    '[Net.Sockets.SocketType]::Stream,' +
    '[Net.Sockets.ProtocolType]::Tcp);' +
    '$socket.ExclusiveAddressUse=$true;' +
    '$socket.Bind([Net.IPEndPoint]::new(' +
    '[Net.IPAddress]::Loopback,' + IntToStr(SelectedPort) + '));' +
    '$code=0}catch{$code=1}finally{' +
    'if($null -ne $socket){$socket.Dispose()}};exit $code"';
  if not Exec(
    PowerShell,
    ProbeCommand,
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ExitCode) or (ExitCode <> 0) then
    Result := ExpandConstant('{cm:EndpointPreflightUnavailable}');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Arguments: String;
  ExitCode: Integer;
  LanguageCode: String;
  TrayValue: String;
  LoginValue: String;
begin
  if CurStep <> ssPostInstall then
    exit;
  if ActiveLanguage = 'italian' then
    LanguageCode := 'it'
  else
    LanguageCode := 'en';
  if WizardIsTaskSelected('traydefault') then
    TrayValue := 'enabled'
  else
    TrayValue := 'disabled';
  if WizardIsTaskSelected('loginstartup') then
    LoginValue := 'enabled'
  else
    LoginValue := 'disabled';
  Arguments := '--initialize-shell-settings --install-port ' + PortPage.Values[0] +
    ' --install-language ' + LanguageCode + ' --install-tray ' + TrayValue +
    ' --install-login-startup ' + LoginValue;
  if not Exec(
    ExpandConstant('{app}\Provelume.exe'),
    Arguments,
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ExitCode) or (ExitCode <> 0) then
  begin
    if not ExistingShellSettings then
    begin
      Exec(
        ExpandConstant('{app}\Provelume.exe'),
        '--remove-login-startup',
        '',
        SW_HIDE,
        ewWaitUntilTerminated,
        ExitCode);
      DeleteFile(ExpandConstant('{localappdata}\Provelume\launcher.json'));
    end;
    RaiseException(ExpandConstant('{cm:EndpointUnavailable}'));
  end;
end;
