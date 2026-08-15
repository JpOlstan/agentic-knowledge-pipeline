[CmdletBinding()]
param(
    [string]$OutputPath = "dist/lambda-trigger.zip",
    [ValidateSet("x86_64", "arm64")]
    [string]$Architecture = "x86_64"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$lockPath = Join-Path $repositoryRoot "uv.lock"
$stagingRoot = Join-Path $repositoryRoot "runtime/lambda-package-$Architecture"
$resolvedOutput = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot $OutputPath))
$allowedOutputRoot = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot "dist"))
$outputDirectory = Split-Path -Parent $resolvedOutput
$platform = if ($Architecture -eq "arm64") {
    "aarch64-manylinux2014"
} else {
    "x86_64-manylinux2014"
}

$allowedOutputPrefix = $allowedOutputRoot.TrimEnd("\", "/") + [System.IO.Path]::DirectorySeparatorChar
if (-not $resolvedOutput.StartsWith($allowedOutputPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputPath must stay inside the repository dist directory"
}
if ([System.IO.Path]::GetExtension($resolvedOutput) -ne ".zip") {
    throw "OutputPath must use the .zip extension"
}

function Get-LockedPackageVersion {
    param(
        [Parameter(Mandatory)]
        [string]$LockContent,
        [Parameter(Mandatory)]
        [string]$PackageName
    )

    $escapedName = [Regex]::Escape($PackageName)
    $pattern = "(?ms)^\[\[package\]\]\s*name = `"$escapedName`"\s*version = `"([^`"]+)`""
    $match = [Regex]::Match($LockContent, $pattern)
    if (-not $match.Success) {
        throw "Package '$PackageName' was not found in uv.lock"
    }
    return "$PackageName==$($match.Groups[1].Value)"
}

function Copy-SourceFile {
    param(
        [Parameter(Mandatory)]
        [string]$RelativePath
    )

    $source = Join-Path $repositoryRoot (Join-Path "src" $RelativePath)
    $destination = Join-Path $stagingRoot $RelativePath
    $destinationDirectory = Split-Path -Parent $destination
    New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

if (Test-Path -LiteralPath $stagingRoot) {
    Remove-Item -LiteralPath $stagingRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null

try {
    $lockContent = Get-Content -Raw -LiteralPath $lockPath
    $packageNames = @(
        "annotated-types",
        "boto3",
        "botocore",
        "jmespath",
        "pydantic",
        "pydantic-core",
        "python-dateutil",
        "s3transfer",
        "six",
        "typing-extensions",
        "typing-inspection",
        "urllib3"
    )
    $pins = @($packageNames | ForEach-Object {
        Get-LockedPackageVersion -LockContent $lockContent -PackageName $_
    })
    $uvArguments = @(
        "pip",
        "install",
        "--target", $stagingRoot,
        "--python-version", "3.12",
        "--python-platform", $platform,
        "--only-binary", ":all:",
        "--no-compile"
    ) + $pins
    & uv @uvArguments
    if ($LASTEXITCODE -ne 0) {
        throw "uv failed to assemble Lambda dependencies"
    }

    $sourceFiles = @(
        "knowledge_agents/__init__.py",
        "knowledge_agents/domain/budgets.py",
        "knowledge_agents/domain/contracts.py",
        "knowledge_agents/domain/enums.py",
        "knowledge_agents/domain/errors.py",
        "knowledge_agents/entrypoints/__init__.py",
        "knowledge_agents/entrypoints/lambda_handler.py"
    )
    foreach ($sourceFile in $sourceFiles) {
        Copy-SourceFile -RelativePath $sourceFile
    }

    Get-ChildItem -LiteralPath $stagingRoot -Recurse -Directory -Filter "__pycache__" |
        Remove-Item -Recurse -Force
    foreach ($pattern in @("*.pyc", "*.pyo")) {
        foreach ($compiledFile in [System.IO.Directory]::EnumerateFiles(
            $stagingRoot,
            $pattern,
            [System.IO.SearchOption]::AllDirectories
        )) {
            [System.IO.File]::Delete($compiledFile)
        }
    }
    $uvTargetLock = Join-Path $stagingRoot ".lock"
    if (Test-Path -LiteralPath $uvTargetLock) {
        Remove-Item -LiteralPath $uvTargetLock -Force
    }

    if (Test-Path -LiteralPath $resolvedOutput) {
        Remove-Item -LiteralPath $resolvedOutput -Force
    }
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archiveStream = [System.IO.File]::Open(
        $resolvedOutput,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
    try {
        $archive = [System.IO.Compression.ZipArchive]::new(
            $archiveStream,
            [System.IO.Compression.ZipArchiveMode]::Create,
            $false
        )
        try {
            $fixedTimestamp = [System.DateTimeOffset]::new(
                2026, 1, 1, 0, 0, 0, [System.TimeSpan]::Zero
            )
            $files = @([System.IO.Directory]::EnumerateFiles(
                $stagingRoot,
                "*",
                [System.IO.SearchOption]::AllDirectories
            ))
            if ($files.Count -eq 0) {
                throw "Lambda staging directory is empty"
            }
            [Array]::Sort($files, [System.StringComparer]::Ordinal)
            foreach ($file in $files) {
                $relativePath = $file.Substring($stagingRoot.Length + 1).Replace("\", "/")
                $entry = $archive.CreateEntry(
                    $relativePath,
                    [System.IO.Compression.CompressionLevel]::Optimal
                )
                $entry.LastWriteTime = $fixedTimestamp
                $entryStream = $entry.Open()
                $inputStream = [System.IO.File]::OpenRead($file)
                try {
                    $inputStream.CopyTo($entryStream)
                } finally {
                    $inputStream.Dispose()
                    $entryStream.Dispose()
                }
            }
        } finally {
            $archive.Dispose()
        }
    } finally {
        $archiveStream.Dispose()
    }

    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedOutput).Hash.ToLowerInvariant()
    Write-Output "lambda_package=$resolvedOutput"
    Write-Output "sha256=$hash"
} finally {
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}
