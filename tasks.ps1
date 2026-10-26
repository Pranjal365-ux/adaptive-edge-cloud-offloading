[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('setup', 'test', 'lint', 'demo', 'demo-offline', 'demo-azure',
        'demo-check', 'down', 'docker-build', 'tf-validate', 'tf-plan', 'preflight')]
    [string]$Task
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Ruff = Join-Path $Root '.venv\Scripts\ruff.exe'
$TaskArgs = $args

function Invoke-External {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Command failed with exit code $LASTEXITCODE" }
}

function Invoke-ComposeWithCloudUrl {
    param([Parameter(Mandatory = $true)][string]$CloudUrl)
    $PreviousCloudUrl = [Environment]::GetEnvironmentVariable('CLOUD_URL', 'Process')
    try {
        $env:CLOUD_URL = $CloudUrl
        Invoke-External 'docker' @('compose', 'up', '-d', '--build', '--wait')
    }
    finally {
        if ($null -eq $PreviousCloudUrl) {
            [Environment]::SetEnvironmentVariable('CLOUD_URL', $null, 'Process')
        }
        else {
            [Environment]::SetEnvironmentVariable('CLOUD_URL', $PreviousCloudUrl, 'Process')
        }
    }
}

Push-Location $Root
try {
    switch ($Task) {
        'setup' {
            if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
                Invoke-External 'py' @('-3.12', '-m', 'venv', '.venv')
            }
            $PythonVersion = & $Python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
            if ($PythonVersion -ne '3.12') {
                throw "The existing .venv uses Python $PythonVersion. Preserve it, rename it to .venv-py$($PythonVersion.Replace('.', '')), then run: py -3.12 -m venv .venv"
            }
            Invoke-External $Python @('-m', 'pip', 'install', '--upgrade', 'pip')
            Invoke-External $Python @('-m', 'pip', 'install', '-e', '.[dev,services]')
        }
        'test' { Invoke-External $Python (@('-m', 'pytest', '--cov=offloader', '--cov-report=term-missing') + $TaskArgs) }
        'lint' {
            Invoke-External $Ruff (@('check', '.') + $TaskArgs)
            Invoke-External $Ruff @('format', '--check', '.')
        }
        'demo' {
            Invoke-ComposeWithCloudUrl -CloudUrl 'http://toxiproxy:8666'
            Start-Process 'http://localhost:8000/console'
        }
        'demo-offline' {
            Invoke-ComposeWithCloudUrl -CloudUrl 'http://cloud:8081'
            Start-Process 'http://localhost:8000/console'
        }
        'demo-azure' {
            if (-not $env:AZURE_WORKER_URL) {
                $env:AZURE_WORKER_URL = [Environment]::GetEnvironmentVariable('AZURE_WORKER_URL', 'User')
            }
            if (-not $env:CLOUD_API_KEY) {
                $env:CLOUD_API_KEY = [Environment]::GetEnvironmentVariable('CLOUD_API_KEY', 'User')
            }
            if (-not $env:AZURE_WORKER_URL) { throw 'Set AZURE_WORKER_URL to the deployed HTTPS worker URL.' }
            if (-not $env:CLOUD_API_KEY) { throw 'Set CLOUD_API_KEY as a Windows user environment variable for the Azure worker.' }
            Invoke-ComposeWithCloudUrl -CloudUrl $env:AZURE_WORKER_URL
            Start-Process 'http://localhost:8000/console'
        }
        'demo-check' { Invoke-External $Python @('scripts\demo_check.py') }
        'down' { Invoke-External 'docker' @('compose', 'down') }
        'docker-build' { Invoke-External 'docker' @('compose', 'build') }
        'tf-validate' {
            Invoke-External 'terraform' @('fmt', '-check', '-recursive', 'infra')
            foreach ($folder in @('infra/bootstrap', 'infra/envs/dev', 'infra/envs/prod')) {
                Invoke-External 'terraform' @("-chdir=$folder", 'init', '-backend=false', '-input=false')
                Invoke-External 'terraform' @("-chdir=$folder", 'validate')
            }
        }
        'tf-plan' {
            if (-not (Test-Path -LiteralPath 'infra\envs\dev\terraform.tfvars')) {
                throw 'Create infra\envs\dev\terraform.tfvars from terraform.tfvars.example before planning.'
            }
            if (-not (Test-Path -LiteralPath 'infra\envs\dev\backend.hcl')) {
                throw 'Create infra\envs\dev\backend.hcl from backend.hcl.example after bootstrap and grant blob access.'
            }
            Invoke-External 'terraform' @('-chdir=infra/envs/dev', 'init', '-backend-config=backend.hcl', '-input=false')
            Invoke-External 'terraform' @('-chdir=infra/envs/dev', 'plan', '-out=offloadops.tfplan')
        }
        'preflight' { Invoke-External $Python @('scripts\preflight.py') }
    }
}
finally { Pop-Location }
