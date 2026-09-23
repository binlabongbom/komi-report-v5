param([Parameter(Mandatory = $true)][string]$InstallDir)

$ErrorActionPreference = 'Stop'
$root = [System.IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
$targets = @(
    [System.IO.Path]::Combine($root, 'runtime', 'python.exe'),
    [System.IO.Path]::Combine($root, 'runtime', 'pythonw.exe'),
    [System.IO.Path]::Combine($root, 'node-runtime', 'node.exe')
)

function Get-InstalledProcesses {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe' OR Name = 'node.exe'" |
        Where-Object {
            $path = $_.ExecutablePath
            $path -and ($targets | Where-Object {
                [string]::Equals($path, $_, [System.StringComparison]::OrdinalIgnoreCase)
            })
        }
}

try {
    # The Runtime Manager cannot release a Node binary while it is running.
    # Match the executable's absolute path so unrelated Python/Node apps stay up.
    foreach ($process in (Get-InstalledProcesses)) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    do {
        $remaining = @(Get-InstalledProcesses)
        if ($remaining.Count -eq 0) { exit 0 }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    exit 1
} catch {
    exit 1
}
