; electron-builder creates the start-menu and desktop shortcuts itself
; (createDesktopShortcut: true), so this file only verifies the payload and
; cleans up the sidecar tree.
;
; electron-builder compiles the uninstaller as a second makensis pass
; (-DBUILD_UNINSTALLER, warnings are errors). Installer-only Vars must not be
; allocated there or makensis exits with warning 6001.

; common.nsh sets ShowInstDetails nevershow, which removes the details button.
; hide keeps the log collapsed until the user expands it on the progress page.
; The function is defined here, after LogicLib is loaded. The uninstaller
; keeps ShowUninstDetails nevershow and does not get this function.
!macro customHeader
  !ifndef BUILD_UNINSTALLER
    ShowInstDetails hide

    Function happyclawAppFilesCopied
      !insertmacro happyclawDetailsOn
      IntCmp $LANGUAGE 2052 happyclaw_files_zh happyclaw_files_en happyclaw_files_en
happyclaw_files_zh:
      DetailPrint "应用程序文件已写入。"
      Goto happyclaw_files_done
happyclaw_files_en:
      DetailPrint "Application files copied."
happyclaw_files_done:
    FunctionEnd
  !endif
!macroend

!macro happyclawDetailsOn
  ${IfNot} ${Silent}
    ; installSection sets this to none, which drops DetailPrint entirely.
    ; textonly only updates the status line above the progress bar, so the
    ; details list stays empty. both fills that list and the status line.
    ; CopyFiles /SILENT and a quiet tar keep the runtime's files out of it.
    SetDetailsPrint both
  ${EndIf}
!macroend

; Do not define customFiles_<arch>. electron-builder emits that macro when
; resources contain a precompressed file and uses it to pack the zip. A second
; definition aborts makensis with "macro named customFiles_x64 already exists".
; customInstall prints the copied-files line after that macro has run.

; Finish page is electron-builder's default one: it offers "run" and the
; shortcut was already created during install.

; Same rule as DeepSeek Harness customCheckAppRunning: match this install's
; executable, not another happyclaw.exe. An update waits up to 10s for the shell
; to leave the tray. Otherwise stop and ask the user to quit. Never taskkill.
!macro customCheckAppRunning
  Push $0
  Push $1
  Push $2
  StrCpy $0 "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
  ${IfNot} ${FileExists} "$0"
    StrCpy $0 "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
  ${EndIf}
  System::Call 'Kernel32::SetEnvironmentVariable(t "HAPPYCLAW_INSTALL_EXE", t "$INSTDIR\${APP_EXECUTABLE_FILENAME}")'
  StrCpy $1 0
happyclaw_run_probe:
  nsExec::Exec `"$0" -NoProfile -NonInteractive -Command "try { $$e = [IO.Path]::GetFullPath([Environment]::GetEnvironmentVariable('HAPPYCLAW_INSTALL_EXE')); $$hit = $$false; Get-CimInstance Win32_Process | ForEach-Object { if ($$_.ExecutablePath) { try { if ([string]::Equals([IO.Path]::GetFullPath($$_.ExecutablePath), $$e, 'OrdinalIgnoreCase')) { $$hit = $$true } } catch {} } }; if ($$hit) { exit 0 } else { exit 1 } } catch { exit 2 }"`
  Pop $2
  IntCmp $2 0 happyclaw_run_alive
  IntCmp $2 1 happyclaw_run_free happyclaw_run_bad happyclaw_run_bad
happyclaw_run_alive:
  ${If} ${isUpdated}
    IntCmp $1 40 happyclaw_run_busy happyclaw_run_wait happyclaw_run_busy
happyclaw_run_wait:
    IntOp $1 $1 + 1
    Sleep 250
    Goto happyclaw_run_probe
  ${EndIf}
happyclaw_run_busy:
  IntCmp $LANGUAGE 2052 happyclaw_run_zh happyclaw_run_en happyclaw_run_en
happyclaw_run_zh:
  MessageBox MB_OK|MB_ICONINFORMATION "${PRODUCT_NAME} 正在运行，请先在系统托盘中退出应用后重试。" /SD IDOK
  Goto happyclaw_run_quit
happyclaw_run_en:
  MessageBox MB_OK|MB_ICONINFORMATION "${PRODUCT_NAME} is running. Quit it from the system tray and try again." /SD IDOK
happyclaw_run_quit:
  SetErrorLevel 2
  Quit
happyclaw_run_bad:
  IntCmp $LANGUAGE 2052 happyclaw_run_bad_zh happyclaw_run_bad_en happyclaw_run_bad_en
happyclaw_run_bad_zh:
  MessageBox MB_OK|MB_ICONEXCLAMATION "无法确认 ${PRODUCT_NAME} 是否仍在运行，请退出应用后重试。" /SD IDOK
  Goto happyclaw_run_quit
happyclaw_run_bad_en:
  MessageBox MB_OK|MB_ICONEXCLAMATION "Could not check whether ${PRODUCT_NAME} is still running. Quit it and try again." /SD IDOK
  Goto happyclaw_run_quit
happyclaw_run_free:
  !insertmacro happyclawDetailsOn
  IntCmp $LANGUAGE 2052 happyclaw_run_log_zh happyclaw_run_log_en happyclaw_run_log_en
happyclaw_run_log_zh:
  DetailPrint "正在安装应用程序文件…"
  Goto happyclaw_run_log_done
happyclaw_run_log_en:
  DetailPrint "Installing application files…"
happyclaw_run_log_done:
  Pop $2
  Pop $1
  Pop $0
!macroend

; The onedir backend is installed with the rest of the resources
; (resources\sidecar\backend). Nothing is extracted here; this only proves the
; payload is complete before the wizard reports success. happyclaw.exe resolves
; _internal relative to itself, so a missing half is a broken install, not a
; degraded one.
!macro customInstall
  Push $0
  Push $1
  !insertmacro happyclawDetailsOn
  Call happyclawAppFilesCopied
  IntCmp $LANGUAGE 2052 happyclaw_rt_log_zh happyclaw_rt_log_en happyclaw_rt_log_en
happyclaw_rt_log_zh:
  DetailPrint "正在检查本地服务文件…"
  Goto happyclaw_rt_log_done
happyclaw_rt_log_en:
  DetailPrint "Checking the local service files…"
happyclaw_rt_log_done:
  StrCpy $0 "$INSTDIR\resources\sidecar\backend"
  IfFileExists "$0\happyclaw.exe" 0 happyclaw_rt_missing
  IfFileExists "$0\_internal\happyclaw\dashboard\index.html" 0 happyclaw_rt_missing
  IntCmp $LANGUAGE 2052 happyclaw_rt_ok_zh happyclaw_rt_ok_en happyclaw_rt_ok_en
happyclaw_rt_ok_zh:
  DetailPrint "本地服务已就绪。"
  Goto happyclaw_rt_end
happyclaw_rt_ok_en:
  DetailPrint "Local service is ready."
  Goto happyclaw_rt_end
happyclaw_rt_missing:
  MessageBox MB_ICONSTOP "安装包中缺少本地服务文件（resources\sidecar\backend）。$\r$\n安装已中止。"
  Pop $1
  Pop $0
  Abort
happyclaw_rt_end:
  ; The desktop product name changed after 0.4, so electron-builder now installs
  ; to $LOCALAPPDATA\Programs\HappyClaw. A pre-rename per-user install would stay
  ; behind as a second copy: its uninstall entry shares this appId (already
  ; repointed by the wizard), so only the stale program files are removed here.
  ; User data lives in HAPPYCLAW_HOME and is never touched.
  StrCpy $1 "$LOCALAPPDATA\Programs\Octop"
  IfFileExists "$1\octop.exe" 0 happyclaw_legacy_dir_done
  IntCmp $LANGUAGE 2052 happyclaw_legacy_dir_zh happyclaw_legacy_dir_en happyclaw_legacy_dir_en
happyclaw_legacy_dir_zh:
  DetailPrint "正在清理改名前的旧安装目录 $1…"
  Goto happyclaw_legacy_dir_rm
happyclaw_legacy_dir_en:
  DetailPrint "Removing the pre-rename install directory $1…"
happyclaw_legacy_dir_rm:
  RMDir /r "$1"
happyclaw_legacy_dir_done:
  Pop $1
  Pop $0
!macroend

!macro customUnInstall
  IfFileExists "$newDesktopLink" 0 happyclaw_un_old_link
    WinShell::UninstShortcut "$newDesktopLink"
    Delete "$newDesktopLink"
happyclaw_un_old_link:
  IfFileExists "$oldDesktopLink" 0 happyclaw_un_sidecar
    WinShell::UninstShortcut "$oldDesktopLink"
    Delete "$oldDesktopLink"
happyclaw_un_sidecar:
  RMDir /r "$INSTDIR\resources\sidecar"
  ; pyc is a cache inside the user-data directory. Drop only that directory;
  ; the next install runs compileall again. Database, workspace, and config stay.
  Push $0
  ReadEnvStr $0 HAPPYCLAW_HOME
  StrCmp $0 "" 0 happyclaw_un_home_legacy
  Goto happyclaw_un_pyc_dir
happyclaw_un_home_legacy:
  ReadEnvStr $0 OCTOP_HOME
  StrCmp $0 "" 0 happyclaw_un_pyc_dir
  StrCpy $0 "$PROFILE\.happyclaw"
  IfFileExists "$0\*.*" happyclaw_un_pyc_dir 0
  StrCpy $0 "$PROFILE\.octop"
  IfFileExists "$0\*.*" happyclaw_un_pyc_dir 0
  StrCpy $0 ""
happyclaw_un_pyc_dir:
  StrCmp $0 "" happyclaw_un_pyc_done
  IntCmp $LANGUAGE 2052 happyclaw_un_pyc_zh happyclaw_un_pyc_en happyclaw_un_pyc_en
happyclaw_un_pyc_zh:
  DetailPrint "正在删除字节码缓存 $0\pyc…"
  Goto happyclaw_un_pyc_rm
happyclaw_un_pyc_en:
  DetailPrint "Removing bytecode cache $0\pyc…"
happyclaw_un_pyc_rm:
  RMDir /r "$0\pyc"
happyclaw_un_pyc_done:
  Pop $0
!macroend
