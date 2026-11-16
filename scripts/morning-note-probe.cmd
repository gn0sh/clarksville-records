@echo off
rem Morning note probe: double-click this file. It runs morning-note-probe.ps1 from the same folder.
rem Docs: docs/ops/morning-note-brian-steps.md. It never saves the key; results go to your OneDrive App Development folder.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0morning-note-probe.ps1"
if errorlevel 1 pause