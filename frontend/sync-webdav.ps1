$ErrorActionPreference = 'Stop'
$config = @{}
Get-Content -LiteralPath (Join-Path $PSScriptRoot '.env') | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
        $config[$matches[1]] = $matches[2].Trim().Trim('"').Trim("'")
    }
}
foreach ($key in @('WEBDAV_URL', 'WEBDAV_USER', 'WEBDAV_PASSWORD')) {
    if (-not $config[$key]) { throw "Missing setting: $key" }
}
Add-Type -AssemblyName System.Net.Http
$client = [System.Net.Http.HttpClient]::new()
$token = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($config.WEBDAV_USER + ':' + $config.WEBDAV_PASSWORD))
$client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new('Basic', $token)
$base = [Uri]($config.WEBDAV_URL.TrimEnd('/') + '/')
$root = Join-Path $PSScriptRoot 'remote-files'
$script:count = 0
$script:skipped = 0
$visited = @{}
function Fetch-Folder([Uri]$uri, [string]$folder) {
    if ($visited.ContainsKey($uri.AbsoluteUri)) { return }
    $visited[$uri.AbsoluteUri] = $true
    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::new('PROPFIND'), $uri)
    $request.Headers.Add('Depth', '1')
    $request.Content = [System.Net.Http.StringContent]::new('<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>', [Text.Encoding]::UTF8, 'application/xml')
    $response = $client.SendAsync($request).GetAwaiter().GetResult()
    if (-not $response.IsSuccessStatusCode) { throw ('WebDAV listing HTTP ' + [int]$response.StatusCode) }
    [xml]$xml = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    $ns = [Xml.XmlNamespaceManager]::new($xml.NameTable)
    $ns.AddNamespace('d', 'DAV:')
    foreach ($entry in $xml.SelectNodes('//d:response', $ns)) {
        $href = $entry.SelectSingleNode('d:href', $ns).InnerText
        $child = [Uri]::new($uri, $href)
        if ($child.AbsolutePath.TrimEnd('/') -eq $uri.AbsolutePath.TrimEnd('/')) { continue }
        if ($child.Authority -ne $base.Authority -or $child.Scheme -ne $base.Scheme -or -not $child.AbsolutePath.StartsWith($base.AbsolutePath, [StringComparison]::Ordinal)) { throw 'Server returned a path outside the configured root.' }
        $name = [Uri]::UnescapeDataString($child.AbsolutePath.TrimEnd('/').Split('/')[-1])
        if ($name -in @('.', '..') -or $name.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0) { throw 'Server returned an unsafe filename.' }
        $target = Join-Path $folder $name
        if ($entry.SelectSingleNode('d:propstat/d:prop/d:resourcetype/d:collection', $ns)) {
            Fetch-Folder $child $target
        } elseif (Test-Path -LiteralPath $target) {
            $script:skipped++
        } else {
            $partial = $target + '.partial'
            & curl.exe --silent --show-error --fail --connect-timeout 20 --max-time 300 --user ($config.WEBDAV_USER + ':' + $config.WEBDAV_PASSWORD) --output $partial $child.AbsoluteUri
            if ($LASTEXITCODE -ne 0) { throw 'Download failed.' }
            Move-Item -LiteralPath $partial -Destination $target
            $script:count++
        }
    }
    $response.Dispose()
    $request.Dispose()
}
try {
    Fetch-Folder $base $root
    Write-Output "Downloaded: $script:count; existing files skipped: $script:skipped"
} catch {
    Write-Output ('Transfer failed (' + $_.Exception.GetType().Name + ').')
    if ($_.Exception.Message -match 'HTTP \d+|Missing setting: \w+|Server returned [^.]+\.') { Write-Output $matches[0] }
    exit 1
} finally { $client.Dispose() }
