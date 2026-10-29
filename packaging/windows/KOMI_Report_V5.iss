#ifndef PayloadDir
  #error PayloadDir must point to the staged KOMI Report V5 payload
#endif
#ifndef OutputDir
  #error OutputDir must point to the RC evidence directory
#endif
#ifndef SourceCommit
  #define SourceCommit "UNCOMMITTED"
#endif
#ifndef OutputBaseFilename
  #define OutputBaseFilename "KOMI_Report_V5_2_14_Windows_x64_RC"
#endif
#ifndef VersionInfoDescription
  #define VersionInfoDescription "KOMI Report V5.2.14 Release Candidate"
#endif
#ifndef EditionLabel
  #define EditionLabel "Online Registration"
#endif

#define AppVersion "5.2.14"
#define AppName "KOMI Report V5"
#define AppPublisher "Wongsakorn Uphonram"
#define AppLauncher "START_KOMI_REPORT.vbs"
#define AppUserModelId "KonicaMinolta.KOMIReport.V5"

[Setup]
AppId={{9C32D937-21A5-4A3A-90AE-F0662E60F24A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion} — {#EditionLabel}
AppPublisher={#AppPublisher}
; Upgrade shutdown runs in PrepareToInstall after the chosen {app} is known.
; AppMutex would block Setup at startup, before that scoped shutdown can run.
DefaultDirName={localappdata}\Programs\KOMI Report V5
DefaultGroupName=KOMI Report V5
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#PayloadDir}\source\Logo.ico
UninstallDisplayIcon={app}\source\Logo.ico
LicenseFile=..\..\LICENSE
VersionInfoVersion=5.2.14.0
VersionInfoDescription={#VersionInfoDescription}
VersionInfoProductName=KOMI Report V5
VersionInfoProductVersion=5.2.14
VersionInfoCompany={#AppPublisher}
VersionInfoCopyright=Copyright (c) 2026 Wongsakorn Uphonram. All Rights Reserved.
UsePreviousAppDir=yes
CloseApplications=yes
RestartApplications=no
ChangesEnvironment=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installer_shutdown.ps1"; Flags: dontcopy

[Icons]
Name: "{autoprograms}\KOMI Report V5"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\{#AppLauncher}"""; WorkingDir: "{app}"; IconFilename: "{app}\source\Logo.ico"; AppUserModelID: "{#AppUserModelId}"
Name: "{autoprograms}\KOMI Report Web"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\source\app.py"" --open-web"; WorkingDir: "{app}"; IconFilename: "{app}\source\Logo.ico"; AppUserModelID: "{#AppUserModelId}"
Name: "{autodesktop}\KOMI Report V5"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\{#AppLauncher}"""; WorkingDir: "{app}"; IconFilename: "{app}\source\Logo.ico"; AppUserModelID: "{#AppUserModelId}"; Tasks: desktopicon
Name: "{autodesktop}\KOMI Report Web"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\source\app.py"" --open-web"; WorkingDir: "{app}"; IconFilename: "{app}\source\Logo.ico"; AppUserModelID: "{#AppUserModelId}"; Tasks: desktopicon
; Upgrade migration: rewrite an existing customer shortcut even when the
; checked-once desktop task is not offered again. A fresh install that opted
; out still receives no Desktop shortcut.
Name: "{autodesktop}\KOMI Report V5"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\{#AppLauncher}"""; WorkingDir: "{app}"; IconFilename: "{app}\source\Logo.ico"; AppUserModelID: "{#AppUserModelId}"; Check: ExistingDesktopShortcut
Name: "{autodesktop}\KOMI Report Web"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\source\app.py"" --open-web"; WorkingDir: "{app}"; IconFilename: "{app}\source\Logo.ico"; AppUserModelID: "{#AppUserModelId}"; Check: ExistingWebShortcut

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Run]
Filename: "{sys}\wscript.exe"; Parameters: """{app}\{#AppLauncher}"""; WorkingDir: "{app}"; Description: "Launch KOMI Report V5"; Flags: nowait postinstall skipifsilent

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
  Command: String;
begin
  Result := '';
  ExtractTemporaryFile('installer_shutdown.ps1');
  Command := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{tmp}\installer_shutdown.ps1') + '" -InstallDir "' +
    ExpandConstant('{app}') + '"';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Command, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
    Result := 'Could not stop the installed KOMI processes. Close KOMI Report and retry Setup.'
  else if ExitCode <> 0 then
    Result := 'KOMI Report is still running from this installation. Close it and retry Setup.';
end;

function ExistingDesktopShortcut(): Boolean;
begin
  Result := FileExists(ExpandConstant('{autodesktop}\KOMI Report V5.lnk'));
end;

function ExistingWebShortcut(): Boolean;
begin
  Result := FileExists(ExpandConstant('{autodesktop}\KOMI Report Web.lnk'));
end;

// User database, backups, logs, Web security material and OS-vault entries are
// intentionally outside {app}. Uninstall removes program files only. Data
// cleanup is a separate, explicit support action after a verified backup.
