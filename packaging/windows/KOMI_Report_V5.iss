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
  #define OutputBaseFilename "KOMI_Report_V5_1_0_Windows_x64_RC"
#endif
#ifndef VersionInfoDescription
  #define VersionInfoDescription "KOMI Report V5.1.0 Release Candidate"
#endif

#define AppVersion "5.1.0"
#define AppName "KOMI Report V5"
#define AppPublisher "Konica Minolta"
#define AppLauncher "START_KOMI_REPORT.vbs"

[Setup]
AppId={{9C32D937-21A5-4A3A-90AE-F0662E60F24A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppMutex=KOMIReportV5.SingleInstance
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
VersionInfoVersion=5.1.0.0
VersionInfoDescription={#VersionInfoDescription}
VersionInfoProductName=KOMI Report V5
VersionInfoProductVersion=5.1.0
VersionInfoCompany=Konica Minolta
VersionInfoCopyright=Source commit {#SourceCommit}
UsePreviousAppDir=yes
CloseApplications=yes
RestartApplications=no
ChangesEnvironment=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\KOMI Report V5"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\{#AppLauncher}"""; WorkingDir: "{app}"; IconFilename: "{app}\source\Logo.ico"
Name: "{autodesktop}\KOMI Report V5"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\{#AppLauncher}"""; WorkingDir: "{app}"; IconFilename: "{app}\source\Logo.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Run]
Filename: "{sys}\wscript.exe"; Parameters: """{app}\{#AppLauncher}"""; WorkingDir: "{app}"; Description: "Launch KOMI Report V5"; Flags: nowait postinstall skipifsilent

; User database, backups, logs, Web security material and OS-vault entries are
; intentionally outside {app}. Uninstall removes program files only. Data
; cleanup is a separate, explicit support action after a verified backup.
