# NSIS Script for installing a Python application packed with PyInstaller.
# NSIS can be installed like `conda install nsis`

# ------------------------------------------------
# Argument Variables
# Pass version and dist dir as an argvar like:
# `makensis -DVERSION="1.2.3" -DDIST="dist/path/" win64_installer.nsi`

!ifdef VERSION
  # do nothing
!else
  !define VERSION "0.0.0"
!endif

# ------------------------------------------------
# Definitions
# Paths relative to THIS File

!define APP_NAME "ParseTrail"
!define SOURCE_DIR "..\build\ParseTrail\*.*"
!define EXE_IN_SOURCE "ParseTrail.exe"
!define OUTPUT_PATH "${DIST}\win64\parsetrail_${VERSION}_win64_setup.exe"
!define INSTALLER_ICON "..\assets\parsetrail_128px.ico"
!define COMPANY_NAME "ParseTrail"
!define APP_REGKEY "Software\${APP_NAME}"
!define UNINSTALL_REGKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

# ------------------------------------------------
# Setup

Name "${APP_NAME} v${VERSION}"
Outfile "${OUTPUT_PATH}"
Icon ${INSTALLER_ICON}
UninstallIcon ${INSTALLER_ICON}
Unicode True
InstallDir "$PROGRAMFILES64\${APP_NAME}"

# Check for a previous installation. If found, use the previous install path instead of 'InstallDir'
InstallDirRegKey HKLM "${APP_REGKEY}" "InstallDir"

# ------------------------------------------------
# Pages

Page components
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

# ------------------------------------------------
# Installation Options

Section "${APP_NAME}"
  # Detect previous installation by checking the registry key
  ReadRegStr $R0 HKLM "${APP_REGKEY}" "InstallDir"
  StrCmp $R0 "" new_install found_previous

  found_previous:
    # Check if the uninstaller exists
    IfFileExists "$R0\uninstall.exe" uninstall_previous skip_uninstall

  uninstall_previous:
    ExecWait '"$R0\uninstall.exe" /S'

    # Wait for the uninstaller to finish (max timeout: 10s)
    Var /GLOBAL timeout
    StrCpy $timeout 0
    loop_check:
      Sleep 500  # Wait 500ms
      IntOp $timeout $timeout + 1
      StrCmp $timeout 20 timeout_reached
      IfFileExists "$R0\uninstall.exe" loop_check
      IfFileExists "$R0\" loop_check
      Goto new_install

  timeout_reached:
    MessageBox MB_ICONEXCLAMATION "Uninstallation did not complete in time. Proceeding with new install."
    Goto new_install

  skip_uninstall:
    MessageBox MB_ICONEXCLAMATION "Previous version found, but uninstaller is missing!"
    Goto new_install

  new_install:
    # Continue with main installation
    SetOutPath $INSTDIR

    # Copy application files
    File /r ${SOURCE_DIR}

    # Create the uninstaller
    WriteUninstaller "$INSTDIR\uninstall.exe"

    # Write application-specific registry keys
    WriteRegStr HKLM "${APP_REGKEY}" "InstallDir" "$INSTDIR"

    # Write uninstall-related registry keys for Windows
    WriteRegStr HKLM "${UNINSTALL_REGKEY}" "DisplayName" "${APP_NAME}"
    WriteRegStr HKLM "${UNINSTALL_REGKEY}" "DisplayIcon" "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "${UNINSTALL_REGKEY}" "DisplayVersion" "${VERSION}"
    WriteRegStr HKLM "${UNINSTALL_REGKEY}" "Publisher" "${COMPANY_NAME}"
    WriteRegStr HKLM "${UNINSTALL_REGKEY}" "InstallLocation" "$INSTDIR"
    WriteRegStr HKLM "${UNINSTALL_REGKEY}" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegDWORD HKLM "${UNINSTALL_REGKEY}" "NoModify" 1
    WriteRegDWORD HKLM "${UNINSTALL_REGKEY}" "NoRepair" 1

SectionEnd

Section "Start Menu Shortcuts"
  SetOutPath $INSTDIR

  # Create Start Menu shortcuts
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk" "$INSTDIR\uninstall.exe"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${EXE_IN_SOURCE}"

SectionEnd

Section "Desktop Shortcut"
  SetOutPath $INSTDIR

  # Create a desktop shortcut
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${EXE_IN_SOURCE}"

SectionEnd

# ------------------------------------------------
# Uninstaller

Section "Uninstall"
  # Remove registry keys
  DeleteRegKey HKLM "${APP_REGKEY}"
  DeleteRegKey HKLM "${UNINSTALL_REGKEY}"

  # Remove shortcuts and start menu folder
  Delete /REBOOTOK "$DESKTOP\${APP_NAME}.lnk"
  RMDir /r /REBOOTOK "$SMPROGRAMS\${APP_NAME}"

  # Remove installation files
  RMDir /r /REBOOTOK "$INSTDIR"

SectionEnd
