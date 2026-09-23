@echo off
rem Atalho de duplo clique para iniciar_tudo.ps1 (backend + frontend + bot).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0iniciar_tudo.ps1" %*
pause
