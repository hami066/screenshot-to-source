param(
    [Parameter(Mandatory = $true)][string]$AppFolder,
    [Parameter(Mandatory = $true)][string]$Output
)

$ErrorActionPreference = "Stop"
$folder = (Resolve-Path -LiteralPath $AppFolder).Path
if (-not (Test-Path -LiteralPath (Join-Path $folder "ScreenshotToSource.exe") -PathType Leaf)) {
    throw "Choose the extracted ScreenshotToSource program directory."
}
if ([IO.Path]::GetExtension($Output) -ne ".wsb") {
    throw "The output file must have a .wsb extension."
}
$folderXml = [Security.SecurityElement]::Escape($folder)
$command = 'powershell.exe -WindowStyle Hidden -NoProfile -NonInteractive -Command "Copy-Item -LiteralPath C:\PortableInput -Destination C:\ScreenshotToSource -Recurse; Start-Process -FilePath C:\ScreenshotToSource\ScreenshotToSource.exe"'
$commandXml = [Security.SecurityElement]::Escape($command)
$config = @"
<Configuration>
  <vGPU>Disable</vGPU>
  <Networking>Disable</Networking>
  <AudioInput>Disable</AudioInput>
  <VideoInput>Disable</VideoInput>
  <ProtectedClient>Enable</ProtectedClient>
  <PrinterRedirection>Disable</PrinterRedirection>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>$folderXml</HostFolder>
      <SandboxFolder>C:\PortableInput</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>$commandXml</Command>
  </LogonCommand>
</Configuration>
"@
Set-Content -LiteralPath $Output -Value $config -Encoding UTF8
