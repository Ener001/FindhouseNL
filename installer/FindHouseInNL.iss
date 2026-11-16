; FindHouseInNL Windows kurulum dosyası (Inno Setup 6)
; GitHub Actions derler:  ISCC /DAppVer=1.<n> installer\FindHouseInNL.iss
#ifndef AppVer
  #define AppVer "1.0"
#endif

[Setup]
AppId={{6F1E5C2B-8B7A-4C4E-9E0B-2D7E3B5A9F11}
AppName=FindHouseInNL
AppVersion={#AppVer}
AppVerName=FindHouseInNL {#AppVer}
AppPublisher=FindHouseInNL
AppPublisherURL=https://ener001.github.io/FindhouseNL/
DefaultDirName={localappdata}\Programs\FindHouseInNL
DefaultGroupName=FindHouseInNL
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=FindHouseInNL-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\FindHouseInNL.exe
UninstallDisplayName=FindHouseInNL
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Masaüstüne simge koy"; GroupDescription: "Simgeler:"
Name: "autostart"; Description: "Bilgisayar açılınca FindHouseInNL de açılsın (yeni ilanları kaçırmamak için)"; GroupDescription: "Diğer:"; Flags: unchecked

[Files]
Source: "..\dist\FindHouseInNL\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; eski sürümden kalan dosyalar karışmasın (kullanıcı verileri başka klasörde, etkilenmez)
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\FindHouseInNL"; Filename: "{app}\FindHouseInNL.exe"
Name: "{group}\FindHouseInNL'i kaldır"; Filename: "{uninstallexe}"
Name: "{autodesktop}\FindHouseInNL"; Filename: "{app}\FindHouseInNL.exe"; Tasks: desktopicon
Name: "{userstartup}\FindHouseInNL"; Filename: "{app}\FindHouseInNL.exe"; Tasks: autostart

[Run]
Filename: "{app}\FindHouseInNL.exe"; Description: "FindHouseInNL'i şimdi aç"; Flags: nowait postinstall

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c taskkill /im FindHouseInNL.exe /f"; Flags: runhidden; RunOnceId: "KillApp"
