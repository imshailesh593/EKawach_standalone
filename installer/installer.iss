; eKavach CBAC Auto-Filler installer (Inno Setup 6)
#define AppName "eKavach CBAC Auto-Filler"
#ifndef AppVer
  #define AppVer "1.0.0"
#endif
#define AppExe  "EkavachFiller.exe"

[Setup]
AppId={{7B1E5C52-3A0D-4F0B-9E57-4C1B0A6D2E91}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher=eKavach Tools
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=no
UsePreviousAppDir=yes
LicenseFile=eula.txt
OutputDir=output
OutputBaseFilename=EkavachFiller_Setup_{#AppVer}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
CloseApplications=yes

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\patients_example.csv"; DestDir: "{app}"; Flags: ignoreversion
Source: "readme.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Open install folder"; Filename: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked

[Registry]
Root: HKA; Subkey: "Software\EkavachFiller"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\EkavachFiller"; ValueType: string; ValueName: "Version"; ValueData: "{#AppVer}"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: WizardSilent
Filename: "{app}"; Description: "Open the install folder"; Flags: postinstall shellexec skipifsilent unchecked

[Code]
var
  SysPage: TOutputMsgMemoWizardPage;
  BrowserFound: Boolean;

function AppPathExists(const Exe: String): Boolean;
var
  Path: String;
  Key: String;
begin
  Key := 'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\' + Exe;
  Result :=
    (RegQueryStringValue(HKLM64, Key, '', Path) and FileExists(Path)) or
    (RegQueryStringValue(HKLM32, Key, '', Path) and FileExists(Path)) or
    (RegQueryStringValue(HKCU, Key, '', Path) and FileExists(Path));
end;

function YesNo(B: Boolean; Yes, No: String): String;
begin
  if B then Result := Yes else Result := No;
end;

procedure InitializeWizard;
var
  V: TWindowsVersion;
  OSName, Report: String;
  Chrome, Edge: Boolean;
  FreeMB, TotalMB: Cardinal;
  DiskOk: Boolean;
begin
  GetWindowsVersionEx(V);
  if V.Build >= 22000 then OSName := 'Windows 11' else OSName := 'Windows 10';

  Chrome := AppPathExists('chrome.exe');
  Edge := AppPathExists('msedge.exe');
  BrowserFound := Chrome or Edge;

  DiskOk := GetSpaceOnDisk(ExtractFileDrive(ExpandConstant('{autopf}')), True, FreeMB, TotalMB) and (FreeMB >= 200);

  Report :=
    'Operating system : ' + OSName + ' (build ' + IntToStr(V.Build) + ')  -  ' + YesNo(True, 'OK', '') + #13#10 +
    'Architecture     : ' + YesNo(IsWin64, '64-bit  -  OK', '32-bit  -  NOT SUPPORTED') + #13#10 +
    'Disk space (C:)  : ' + IntToStr(FreeMB) + ' MB free  -  ' + YesNo(DiskOk, 'OK (needs 200 MB)', 'LOW') + #13#10 +
    'Google Chrome    : ' + YesNo(Chrome, 'Found', 'Not found') + #13#10 +
    'Microsoft Edge   : ' + YesNo(Edge, 'Found', 'Not found') + #13#10 + #13#10 +
    'Other runtimes (Python, Playwright, VC++) are bundled inside the app - nothing else to install.' + #13#10 + #13#10;

  if BrowserFound then
    Report := Report + 'Result: all prerequisites are satisfied.'
  else
    Report := Report + 'Result: NO supported browser found. The app needs Google Chrome or Microsoft Edge. ' +
      'Setup will offer to open the Chrome download page.';

  SysPage := CreateOutputMsgMemoPage(wpLicense, 'System check',
    'Setup has inspected this computer', 'Detected configuration:', Report);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Err: Integer;
begin
  Result := True;
  if (CurPageID = SysPage.ID) and (not BrowserFound) then
  begin
    case MsgBox('Neither Google Chrome nor Microsoft Edge was found.' + #13#10 +
                'The app cannot run without one of them.' + #13#10#13#10 +
                'Open the Chrome download page now?' + #13#10 +
                '(Yes = open page and continue installing, No = continue anyway, Cancel = stay here)',
                mbConfirmation, MB_YESNOCANCEL) of
      IDYES: ShellExec('open', 'https://www.google.com/chrome/', '', '', SW_SHOWNORMAL, ewNoWait, Err);
      IDCANCEL: Result := False;
    end;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
    WizardForm.FinishedLabel.Caption :=
      '{#AppName} was installed in:' + #13#10#13#10 + ExpandConstant('{app}') + #13#10#13#10 +
      'Settings and your licence are stored in:' + #13#10 + ExpandConstant('{userappdata}\EkavachFiller') + #13#10#13#10 +
      'On first launch the app shows your Machine ID - send it to the vendor to receive a licence key.';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { never delete user data in a silent uninstall }
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
    if MsgBox('Also delete saved settings and the licence key for this user?' + #13#10 +
              ExpandConstant('{userappdata}\EkavachFiller'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{userappdata}\EkavachFiller'), True, True, True);
end;
