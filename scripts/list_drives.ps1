Get-CimInstance Win32_LogicalDisk | ForEach-Object {
    $size = [math]::Round($_.Size / 1GB)
    $free = [math]::Round($_.FreeSpace / 1GB)
    Write-Host "$($_.DeviceID) $($_.VolumeName) Size:${size}GB Free:${free}GB"
}
