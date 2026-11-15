; Inno Setup script - builds FlowType-Setup.exe (a normal Windows installer).
; GitHub Actions runs:  iscc /DMyAppVersion=1.4.0 scripts\windows\FlowType-installer.iss
#ifndef MyAppVersion
  #define MyAppVersion "dev"
#endif

[Setup]
AppId={{8C6F2A0E-4C2B-4E77-9B1E-6F0B7C1A2D3F}
AppName=FlowType
AppVersion={#MyAppVersion}
AppVerName=FlowType {#MyAppVersion}
AppPublisher=Soumya Swarup Sahoo
AppPublisherURL=https://github.com/soumyaswarrup/FlowType
AppSupportURL=https://github.com/soumyaswarrup/FlowType/issues
DefaultDirName={localappdata}\Programs\FlowType
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=FlowType-Setup
SetupIconFile=..\..\flowtype.ico
UninstallDisplayIcon={app}\FlowType.exe
UninstallDisplayName=FlowType - voice typing
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\..\LICENSE

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start FlowType automatically when I sign in"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\..\dist\FlowType\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\FlowType"; Filename: "{app}\FlowType.exe"; Comment: "Talk instead of typing"
Name: "{userdesktop}\FlowType"; Filename: "{app}\FlowType.exe"; Tasks: desktopicon
Name: "{userstartup}\FlowType"; Filename: "{app}\FlowType.exe"; Tasks: startup

[Run]
Filename: "{app}\FlowType.exe"; Description: "Start FlowType now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im FlowType.exe"; Flags: runhidden; RunOnceId: "StopFlowType"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  { stop a running copy so it can be updated }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/f /im FlowType.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
