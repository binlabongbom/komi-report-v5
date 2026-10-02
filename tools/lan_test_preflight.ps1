param(
    [string]$PeerIP = '',
    [ValidateRange(1,65535)][int]$WebPort = 3000
)
# Read-only LAN diagnostics. Does not alter firewall, services or certificates.
$ErrorActionPreference = 'Stop'
Get-NetConnectionProfile | Select-Object InterfaceAlias, NetworkCategory, IPv4Connectivity
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in @($WebPort,37853) } |
    Select-Object LocalAddress, LocalPort, OwningProcess
Get-NetUDPEndpoint -ErrorAction SilentlyContinue |
    Where-Object LocalPort -eq 37852 |
    Select-Object LocalAddress, LocalPort, OwningProcess
if ($PeerIP) {
    $peerAddress = [System.Net.IPAddress]::Parse($PeerIP)
    if ($peerAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
        throw 'Use the IPv4 address of the test peer.'
    }
    foreach ($peerPort in @($WebPort,37853) | Select-Object -Unique) {
        $peerSocket = [System.Net.Sockets.TcpClient]::new()
        try {
            $pendingConnection = $peerSocket.ConnectAsync($peerAddress,$peerPort)
            $connected = $pendingConnection.Wait(3000) -and $peerSocket.Connected
            [pscustomobject]@{ Peer=$PeerIP; Port=$peerPort; TCP=$connected }
        } catch {
            [pscustomobject]@{ Peer=$PeerIP; Port=$peerPort; TCP=$false }
        } finally { $peerSocket.Dispose() }
    }
}
Write-Output 'TCP success only proves reachability. Verify TLS, membership, UDP discovery and receipts in the app.'
