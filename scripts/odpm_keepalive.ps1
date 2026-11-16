# Hold a Windows-side wsl.exe session so Debian is not powered off.
# A one-shot wsl.exe exit makes systemd-logind power the distro off
# ("The system will power off now!"), which stops dockerd and the containers.
# Data volume is not touched.
# Arguments have no spaces: Windows PowerShell 5.1 Start-Process does not quote them.
$ErrorActionPreference = 'Stop'
$marker = '/bin/sleep'
function Get-Keepalive {
    @(Get-CimInstance Win32_Process -Filter "Name = 'wsl.exe'" |
        Where-Object { $_.CommandLine -and ($_.CommandLine -match [regex]::Escape($marker)) -and ($_.CommandLine -match 'infinity') })
}
$hit = Get-Keepalive
if (-not $hit) {
    Start-Process -WindowStyle Hidden -FilePath "$env:SystemRoot\System32\wsl.exe" -ArgumentList @(
        '-d', 'Debian', '--', '/bin/sleep', 'infinity'
    ) | Out-Null
}
$deadline = (Get-Date).AddSeconds(30)
do {
    $hit = Get-Keepalive
    if ($hit.Count -gt 0) {
        Write-Output "wh40k-wsl-keepalive pid=$($hit[0].ProcessId)"
        exit 0
    }
    Start-Sleep -Milliseconds 400
} while ((Get-Date) -lt $deadline)
Write-Error 'wh40k-wsl-keepalive did not start'
exit 1
