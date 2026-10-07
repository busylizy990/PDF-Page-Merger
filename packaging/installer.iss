; PDF Page Merger -- Inno Setup script
;
; Packages the PyInstaller output into a single setup .exe with a Start Menu
; entry and an uninstaller.
;
; There is deliberately no [Registry] section and no Explorer right-click menu.
; One was written and dropped unused on 2 October 2026: it covered only 4 of the
; 25 supported extensions, and a multi-file selection would have opened one
; window per file, because Windows invokes a "%1" verb once per item. Doing it
; properly needs a single-instance app with inter-process forwarding, and it
; would hand files over in Explorer's sort order -- the opposite of what a tool
; built around deliberate page order wants. A shortcut in shell:sendto gives the
; same convenience with correct multi-file behaviour and no registry writes.
; See PROJECT-NOTES.md, "Packaging".
;
; Not compiled by hand: packaging\build.ps1 runs PyInstaller, signs the
; executables, compiles this, then signs the installer. Signing the programs
; BEFORE they are packaged matters -- signing the installer alone leaves the
; executables inside it unsigned.
;
; Compile manually with:  ISCC.exe packaging\installer.iss

#define AppName        "PDF Page Merger"
#define AppVersion     "1.0.0"
; Publisher must match the subject on your code signing certificate, or the
; installer's stated publisher and its signature will disagree. Change this
; before a signed build.
#define AppPublisher   "Damreb Consultancy Ltd"
; No AppPublisherURL / AppSupportURL is set below on purpose: Inno shows them
; as the publisher and support links in Add/Remove Programs, and a link that
; goes nowhere is worse than none. Add a #define AppUrl and restore those two
; [Setup] lines once there is a real site to point at.
#define GuiExe         "PDF Page Merger.exe"
#define CliExe         "pdfmerge.exe"

[Setup]
AppId={{7C4B2F9E-5D3A-4E1B-9C68-2A7F4D8E1B03}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=PDFPageMerger-{#AppVersion}-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#GuiExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Per-machine when run as administrator, per-user otherwise, so it installs
; without admin rights where a locked-down machine requires that.
PrivilegesRequiredOverridesAllowed=dialog

; The terms the program is supplied on. The wizard shows these on an
; accept/decline page and refuses to continue without acceptance.
; THIRD-PARTY-NOTICES.txt is not a substitute -- that covers the components this
; program is built from, not the terms it is sold under, and both ship.
;
; EULA.rtf is GENERATED from ..\LICENCE-TERMS.md by packaging\make_eula.py, which
; build.ps1 runs before this script. Edit the Markdown, never the .rtf: two
; copies of a legal document will eventually disagree, and the one the customer
; accepted is this one. The Markdown still has unfilled placeholders -- entity
; name, address, contact -- and make_eula.py lists them on every run.
LicenseFile=EULA.rtf
; 64-bit only, matching the Python that PyInstaller bundles.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
; The whole PyInstaller folder, executables and bundled Python together.
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; The documentation, taken from the source tree rather than from the build.
; PyInstaller would bury anything it packaged under _internal\, where nobody
; looks. These belong beside the programs -- and the third one belongs in the
; input\ folder the tool actually watches, which also creates that folder so a
; fresh install explains itself before the first run.
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
; From docs\, not the project root. The root copy was renamed to order.txt three
; times -- which is exactly what README tells a user to do with the installed one
; -- and each time it removed a build input and the build died at this step. Keep
; the canonical copy away from where anyone works. It still installs to {app}.
Source: "..\docs\order.txt.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\input\READ ME - put PDFs here.txt"; DestDir: "{app}\input"; Flags: ignoreversion

; Required, not optional: the bundled Python, pypdf, Pillow and Tcl/Tk are all
; distributed under licences that oblige their text to travel with the binary.
; Regenerate with:  .python\python.exe packaging\make_notices.py
Source: "..\THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion

; The licence the user accepted during setup, left on disk so they can read it
; again afterwards. The accept page is RTF; this is the readable original.
Source: "..\LICENCE-TERMS.md"; DestDir: "{app}"; Flags: ignoreversion
; Clause 8.3 promises the privacy notice on request and names this file, so
; it travels with the terms rather than leaving that reference dangling.
Source: "..\PRIVACY-NOTICE.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#GuiExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#GuiExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#GuiExe}"; Description: "Open {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Settings are written next to the program when that is writable. Anything the
; user saved in their own profile is deliberately left alone.
Type: files; Name: "{app}\settings.json"
