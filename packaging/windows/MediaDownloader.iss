; Current-user installer. Never deletes the user data or download directories.
#ifndef PayloadDir
  #error PayloadDir is required
#endif
#ifndef ReleaseDir
  #error ReleaseDir is required
#endif
#define ReleaseVersion "0.2.0-preview.12"
#define PayloadVersion "0.2.0-preview.12"
#ifdef QA
  #define ProductName "Media Downloader Installer QA"
#else
  #define ProductName "Media Downloader"
#endif

[Setup]
#ifdef QA
AppId={{B3EE607A-217F-4CBA-9037-A5C55D366932}
#else
AppId={{8F5574CB-A715-4BA1-AD07-4212A70D460B}
#endif
AppName={#ProductName}
AppVersion={#ReleaseVersion}
AppVerName=Media Downloader {#ReleaseVersion}
AppPublisher=Media Downloader Project
VersionInfoVersion=0.2.0.12
DefaultDirName={localappdata}\Programs\MediaDownloader
DefaultGroupName={#ProductName}
PrivilegesRequired=lowest
SetupArchitecture=x64
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
WizardStyle=modern
DisableProgramGroupPage=yes
DisableDirPage=auto
UsePreviousAppDir=yes
UsePreviousTasks=yes
SetupIconFile={#PayloadDir}\Assets\AppIcon.ico
UninstallDisplayIcon={app}\versions\{#PayloadVersion}\MediaDownloader.exe
UninstallDisplayName={#ProductName}
#ifdef QA
AppMutex=Local\MediaDownloader.InstallerQA.Running
#else
AppMutex=Local\MediaDownloader.Native.Running
#endif
SetupMutex=MediaDownloader.Installer.8F5574CB
CloseApplications=no
RestartApplications=no
OutputDir={#ReleaseDir}
#ifdef QA
OutputBaseFilename=MediaDownloader-{#ReleaseVersion}-win-x64-QA-Setup
#else
OutputBaseFilename=MediaDownloader-{#ReleaseVersion}-win-x64-Setup
#endif
Compression=lzma2/max
SolidCompression=yes
LZMADictionarySize=131072
LZMANumBlockThreads=1
DiskSpanning=no
Uninstallable=yes
InfoBeforeFile=InstallInfo.txt

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}\versions\{#PayloadVersion}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "InstallInfo.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#ProductName}"; Filename: "{app}\versions\{#PayloadVersion}\MediaDownloader.exe"; WorkingDir: "{app}\versions\{#PayloadVersion}"
Name: "{autodesktop}\{#ProductName}"; Filename: "{app}\versions\{#PayloadVersion}\MediaDownloader.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\versions\{#PayloadVersion}\MediaDownloader.exe"; Description: "启动 Media Downloader"; Flags: nowait postinstall skipifsilent

; No UninstallDelete section: unknown files, task databases, credentials and downloads are retained.

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
#ifndef QA
  if RegKeyExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{3D263939-3941-508D-B62D-8D39C441EB61}') or
     RegKeyExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{3EB8D870-6330-5752-B6BD-0B3D1CC12A49}') or
     RegKeyExists(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{58A7D313-54D5-57E0-A844-DA165F6FC84B}') then
  begin
    SuppressibleMsgBox('请先在 Windows 设置中卸载旧版 MSI 安装，再安装此版本。任务、Cookie 和下载文件会保留。', mbError, MB_OK, IDOK);
    Result := False;
  end;
#endif
end;


