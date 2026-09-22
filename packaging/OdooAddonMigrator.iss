#define MyAppName "Odoo Addon Migrator"
#ifndef MyAppVersion
#define MyAppVersion "1.0.0rc2"
#endif
#define MyAppExeName "OdooAddonMigrator.exe"

[Setup]
AppId={{6A8E1A19-95A6-4E43-9A74-8BBA6BD8D8A7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Independent project
DefaultDirName={localappdata}\Programs\OdooAddonMigrator
DefaultGroupName={#MyAppName}
OutputDir=..\dist
OutputBaseFilename=OdooAddonMigrator_Setup
PrivilegesRequired=lowest
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "..\dist\OdooAddonMigrator\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
