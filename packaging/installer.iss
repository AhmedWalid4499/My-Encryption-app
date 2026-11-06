; Inno Setup script - builds VeilMark-Setup.exe from dist\VeilMark
; Usage (from the repository root):  iscc packaging\installer.iss
#define AppName "VeilMark"
#ifndef AppVersion
  #define AppVersion "1.5.2"
#endif

[Setup]
AppId={{6B3F2C9E-8E7A-4C61-9B0B-5E2F1A7D4C11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Ahmed Walid
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=VeilMark-Setup
CloseApplications=yes
RestartApplications=no
SetupIconFile=..\assets\veilmark.ico
UninstallDisplayIcon={app}\VeilMark.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\VeilMark\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\VeilMark.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\VeilMark.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VeilMark.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; after a silent in-app update, reopen VeilMark automatically
Filename: "{app}\VeilMark.exe"; Flags: nowait; Check: ShouldRelaunch

[Code]
{ Reopen VeilMark after a silent in-app update, unless /NOLAUNCH is given (used by the CI install test). }
function ShouldRelaunch: Boolean;
var
  i: Integer;
begin
  Result := WizardSilent;
  for i := 1 to ParamCount do
    if CompareText(ParamStr(i), '/NOLAUNCH') = 0 then
      Result := False;
end;
