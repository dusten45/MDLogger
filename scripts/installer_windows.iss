; ---------------------------------------------------------------------
; MDLogger Windows 설치 프로그램 (Inno Setup 6)
;
; 용도: PyInstaller onedir 산출물( dist\MDLogger\ )을 Program Files에
;       설치하고 시작 메뉴 / 바탕화면 바로가기 + 제거 프로그램을 만든다.
;
; 빌드 방법 (Inno Setup 6 설치 후 ISCC.exe 필요):
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" scripts\installer_windows.iss
;
; 주의: 이 파일은 공식 Windows 설치 프로그램 스크립트로 git에 추적된다.
;       빌드 절차는 docs/release.md 의 "Windows exe 배포판 빌드"를 따른다.
; ---------------------------------------------------------------------

; 버전은 src\mdlogger\_version.py 의 __version__ 과 일치해야 한다.
; 수동 동기화가 번거로우면 빌드 스크립트에서 아래 버전 정의를 주입한다:
;   ISCC.exe /DMyAppVersion=1.0.0 scripts\installer_windows.iss
#ifndef MyAppVersion
    #define MyAppVersion "1.0.0"
#endif
#define MyAppName "MDLogger"
#define MyAppExeName "MDLogger.exe"
#define MyAppPublisher "dusten45"
#define MyAppURL "https://github.com/dusten45/MDLogger"

[Setup]
; 세계적으로 고유한 AppId. 최초 생성 후엔 바꾸지 않고 유지해야 갱신 시
; "같은 프로그램"으로 인식된다. (분산 배포 전엔 한번 생성해 상수로 고정)
AppId={{F0987F41-0A8B-4B2E-9C61-9CDD4F8E7C00}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
; Program Files 설치. 관리자 권한 필요(UAC). per-user 설치를 원하면
; DefaultDirName={localappdata}\Programs\{#MyAppName},
; PrivilegesRequired=lowest 로 바꾼다.
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Program Files 는 관리자 권한이 필요하므로 admin 이 안전하다.
PrivilegesRequired=admin
; 설치 프로그램(마법사) 아이콘 — Windows/Inno용이므로 .ico 를 사용한다.
; 같은 그림의 .png(icon\DuelistCup.png)는 앱 자체/다른 OS 배포에서 쓴다.
SetupIconFile=..\icon\DuelistCup.ico
OutputDir=..\dist\installer
OutputBaseFilename=MDLoggerSetup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 작업:"
; Name: "startmenu"; Description: "시작 메뉴에 바로가기 만들기"; GroupDescription: "추가 작업:"

[Files]
; onedir 폴더 전체( _internal\ 포함)를 설치.
; 체크섬 manifest는 기본적으로 `dist\MDLogger.sha256`(폴더 바깥)에 있으므로
; 여기로 복사되지 않는다. 재차 잡는 Excludes 는 폴더 안에 .sha256 이
; 섞이는 경우를 위한 안전망이다(런타임에 불필요). 만약 릴리스 기록으로
; manifest 를 함께 설치하고 싶으면 아래 Source 항목 하나를 추가하면 된다:
;   Source: "..\dist\MDLogger.sha256"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\MDLogger\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.sha256"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{group}\{#MyAppName} 제거"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 사용자 데이터(SQLite)는 OS 표준 데이터 디렉터리에 있으므로 제거 대상이 아니다.
; (데이터를 함께 지우고 싶으면 여기에 그 디렉터리를 추가할 것.)
