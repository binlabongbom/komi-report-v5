@echo off
setlocal EnableExtensions
rem Desktop owns the Web service and opens the LAN IP after it is ready.
call "%~dp0START_KOMI_REPORT.cmd" web
exit /b %ERRORLEVEL%
