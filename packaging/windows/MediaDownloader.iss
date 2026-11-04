; Current-user installer. Never deletes the user data or download directories.
#ifndef PayloadDir
  #error PayloadDir is required
#endif
#ifndef ReleaseDir
  #error ReleaseDir is required
#endif
#define ReleaseVersion "0.2.0-preview.3"
#define PayloadVersion "0.2.0-preview.3"

[Setup]
AppId={{8F5574CB-A715-4BA1-AD07-4212A70D460B}
AppName=Media Downloader
AppVersion={#ReleaseVersion}
AppVerName=Media Downloader {#ReleaseVersion}
AppPublisher=Media Downloader Project
VersionInfoVersion=0.2.0.3
DefaultDirName={localappdata}\Programs\MediaDownloader
DefaultGroupName=Media Downloader
PrivilegesRequired=lowest
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
UninstallDisplayName=Media Downloader
AppMutex=Local\MediaDownloader.Native.Running
SetupMutex=MediaDownloader.Installer.8F5574CB
CloseApplications=no
RestartApplications=no
OutputDir={#ReleaseDir}
OutputBaseFilename=MediaDownloader-0.2.0-preview.3-win-x64-Setup
Compression=lzma2/fast
SolidCompression=yes
LZMANumBlockThreads=2
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
Name: "{autoprograms}\Media Downloader"; Filename: "{app}\versions\{#PayloadVersion}\MediaDownloader.exe"; WorkingDir: "{app}\versions\{#PayloadVersion}"
Name: "{autodesktop}\Media Downloader"; Filename: "{app}\versions\{#PayloadVersion}\MediaDownloader.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\versions\{#PayloadVersion}\MediaDownloader.exe"; Description: "启动 Media Downloader"; Flags: nowait postinstall skipifsilent

; No UninstallDelete section: unknown files, task databases, credentials and downloads are retained.


