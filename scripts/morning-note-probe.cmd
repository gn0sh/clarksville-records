@echo off
rem Morning note probe: double-click this file. It runs morning-note-probe.ps1 from the same folder.
rem Docs: docs/ops/morning-note-brian-steps.md. It never saves the key; results go to Documents\App Development.
rem Local scripts run under RemoteSigned. A downloaded copy may need Unblock: right-click both files > Properties > tick Unblock > OK.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -File "%~dp0morning-note-probe.ps1"
if errorlevel 1 pause