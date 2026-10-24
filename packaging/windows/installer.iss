; Inno Setup Script for Media Manager (Windows x64)
#define MyAppName "Media Manager"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "ValeryJL"
#define MyAppURL "https://github.com/ValeryJL/media_manager"

[Setup]
AppId={{8F6D5A12-4B9E-4C2A-9D31-7A2E5C91B402}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\Media Manager
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist
OutputBaseFilename=MediaManager-Setup-{#MyAppVersion}-Windows-x64
SetupIconFile=..\..\dist\icons\media_manager.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "..\..\media_manager\*"; DestDir: "{app}\src\media_manager"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\setup.py"; DestDir: "{app}\src"; Flags: ignoreversion
Source: "..\..\install.ps1"; DestDir: "{app}\src"; Flags: ignoreversion
Source: "..\..\README.md"; DestDir: "{app}\src"; Flags: ignoreversion
Source: "..\..\dist\icons\media_manager.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "powershell.exe"; Parameters: "-NoProfile -WindowStyle Hidden -Command ""& '{cmd}' /c media-manager-gui"""; IconFilename: "{app}\media_manager.ico"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\src\install.ps1"" -AllUsers"; StatusMsg: "Configurando entorno Python, aria2c y aplicación de escritorio Media Manager..."; Flags: runhidden waituntilterminated; Check: IsAdminInstallMode
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\src\install.ps1"" -CurrentUser"; StatusMsg: "Configurando entorno Python, aria2c y aplicación de escritorio Media Manager..."; Flags: runhidden waituntilterminated; Check: not IsAdminInstallMode
