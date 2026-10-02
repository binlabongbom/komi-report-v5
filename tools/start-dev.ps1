. (Join-Path $PSScriptRoot 'activate-dev.ps1')
Start-Process -FilePath (Join-Path $komiPythonDirectory 'pythonw.exe') `
    -ArgumentList ('"' + (Join-Path $env:KOMI_SOURCE_ROOT 'app.py') + '"') `
    -WorkingDirectory $env:KOMI_SOURCE_ROOT
