[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$qgisAssetsRoot = Split-Path -Parent $PSCommandPath
$repositoryRoot = Split-Path -Parent $qgisAssetsRoot
$workRoot = Split-Path -Parent $repositoryRoot
$projectRoot = Split-Path -Parent $workRoot
$qgisRuntimeRoot = Join-Path $workRoot "tools\QGIS-3.44.13\QGIS 3.44.13"
$sessionRoot = Join-Path $projectRoot "99_临时文件\qgis-gui"
$profileRoot = Join-Path $sessionRoot "profiles-final"
$environmentFile = Join-Path $repositoryRoot ".env"
$pluginSource = Join-Path $qgisAssetsRoot "plugins\dayu_tiangong_bridge"
$profilePlugins = Join-Path $profileRoot "profiles\dayu-gui-final\python\plugins"

function Mount-VerifiedSubstDrive {
    param(
        [Parameter(Mandatory = $true)][string]$Drive,
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$Probe
    )

    $driveRoot = "${Drive}:\"
    $probePath = "${driveRoot}${Probe}"
    if (Test-Path -LiteralPath $probePath) {
        return
    }
    if (Test-Path -LiteralPath $driveRoot) {
        throw "Drive ${Drive}: is already in use. Close this launcher and free that drive letter first."
    }
    & subst.exe "${Drive}:" $Target
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $probePath)) {
        throw "Unable to mount ${Drive}: for the QGIS runtime."
    }
}

if (-not (Test-Path -LiteralPath $environmentFile)) {
    throw "Missing repository .env file. Initialize the local environment first."
}

New-Item -ItemType Directory -Force -Path $sessionRoot, $profileRoot, $profilePlugins | Out-Null
Copy-Item -LiteralPath $pluginSource -Destination $profilePlugins -Recurse -Force
Mount-VerifiedSubstDrive -Drive "Q" -Target $qgisRuntimeRoot -Probe "bin\qgis-ltr.bat"
Mount-VerifiedSubstDrive -Drive "R" -Target $sessionRoot -Probe "profiles-final"
Mount-VerifiedSubstDrive -Drive "S" -Target $repositoryRoot -Probe "qgis\projects\dayu_tiangong_ltr.qgs"

$environmentValues = @{}
foreach ($line in Get-Content -LiteralPath $environmentFile -Encoding UTF8) {
    $separatorIndex = $line.IndexOf("=")
    if ($separatorIndex -gt 0 -and -not $line.TrimStart().StartsWith("#")) {
        $key = $line.Substring(0, $separatorIndex).Trim()
        $value = $line.Substring($separatorIndex + 1)
        $environmentValues[$key] = $value
    }
}

$editorCredentialValue = $environmentValues["QGIS_EDITOR_DB_PASSWORD"]
if ($null -eq $editorCredentialValue) {
    throw "QGIS_EDITOR_DB_PASSWORD is not configured in the ignored .env file."
}

if ([string]::IsNullOrWhiteSpace($editorCredentialValue)) {
    throw "QGIS_EDITOR_DB_PASSWORD is empty in the ignored .env file."
}

[Environment]::SetEnvironmentVariable("PGPASSWORD", $editorCredentialValue, "Process")
$env:PGSERVICEFILE = "S:\qgis\docs\pg_service.conf.example"
$arguments = @(
    "/d",
    "/c",
    "S:\qgis\Start_Dayu_QGIS_Runtime.cmd --noversioncheck --profiles-path R:\profiles-final --profile dayu-gui-final --code S:\qgis\Start_Dayu_QGIS.py -p S:\qgis\projects\dayu_tiangong_ltr.qgs"
)
# Keep this launcher alive for the whole QGIS session.  The synchronous runtime
# wrapper avoids the official batch file's detached ``start /B`` process, so the
# short subst drives remain available while Qt/Python load DLLs and plugins.
Start-Process -FilePath "cmd.exe" -ArgumentList $arguments -Wait
