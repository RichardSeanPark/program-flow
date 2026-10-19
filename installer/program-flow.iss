#define AppVersion "0.2.6"

[Setup]
AppId={{a2445bb1-29c4-4604-9f2e-79980d0ae0d4}
AppName=Program Flow
AppVersion={#AppVersion}
AppPublisher=Program Flow
DefaultDirName={localappdata}\Programs\ProgramFlow
DefaultGroupName=Program Flow
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=ProgramFlow-Setup-{#AppVersion}-x64
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\ProgramFlow.exe
WizardStyle=modern

[Files]
Source: "..\.build\release\ProgramFlow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Program Flow"; Filename: "{app}\ProgramFlow.exe"
Name: "{autodesktop}\Program Flow"; Filename: "{app}\ProgramFlow.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "바탕화면 바로가기 만들기"; GroupDescription: "추가 선택:"

[Run]
Filename: "{app}\ProgramFlow.exe"; Description: "Program Flow 실행"; Flags: nowait postinstall skipifsilent
