$ErrorActionPreference = 'Stop'

$sourceRoot = 'P:\Projects'
$backupRoot = 'E:\'
$expectedSourceDisk = '0000_0000_0000_0000_0C82_D500_3010_9761.'
$expectedBackupDisk = '6551381104375325317'
$localLogDir = Join-Path $env:LOCALAPPDATA 'LOCI'
$localLog = Join-Path $localLogDir 'removable-mirror.log'
New-Item -ItemType Directory -Force -Path $localLogDir | Out-Null

function Write-MirrorLog([string]$message) {
  $line = ('{0:u} {1}' -f (Get-Date), $message)
  Add-Content -LiteralPath $localLog -Value $line
  if (Test-Path -LiteralPath 'P:\Projects\_snapshots') {
    Add-Content -LiteralPath 'P:\Projects\_snapshots\removable-mirror.log' -Value $line
  }
}

try {
  $sourceVolume = Get-Volume -DriveLetter P
  $backupVolume = Get-Volume -DriveLetter E
  if ($sourceVolume.FileSystem -ne 'NTFS' -or $sourceVolume.FileSystemLabel -ne 'Projects-Backup') {
    throw 'P: volume identity or filesystem mismatch'
  }
  if ($backupVolume.FileSystem -ne 'NTFS' -or $backupVolume.FileSystemLabel -ne 'LOCI-Drive') {
    throw 'E: volume identity or filesystem mismatch'
  }
  $sourcePartition = Get-Partition -DriveLetter P
  $backupPartition = Get-Partition -DriveLetter E
  $sourceDisk = Get-Disk -Number $sourcePartition.DiskNumber
  $backupDisk = Get-Disk -Number $backupPartition.DiskNumber
  if ($sourceDisk.SerialNumber -ne $expectedSourceDisk) {
    throw 'P: disk serial mismatch; refusing to write to E:'
  }
  if ($backupDisk.SerialNumber -ne $expectedBackupDisk) {
    throw 'E: disk serial mismatch; refusing to write to removable media'
  }
  if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
    throw 'P:\Projects is not available'
  }

  & robocopy $sourceRoot $backupRoot /MIR /COPY:DAT /DCOPY:DAT /R:2 /W:5 /XJ /Z /FFT /NP /NFL /NDL /NJH /NJS /XD 'E:\System Volume Information' 'E:\$RECYCLE.BIN' /LOG+:$localLog
  $copyCode = $LASTEXITCODE
  if ($copyCode -ge 8) {
    throw "robocopy failed with exit code $copyCode"
  }
  Write-MirrorLog ('mirror complete; robocopy exit code ' + $copyCode)
  exit 0
} catch {
  Write-MirrorLog ('mirror blocked/failed; ' + $_.Exception.Message)
  exit 1
}
