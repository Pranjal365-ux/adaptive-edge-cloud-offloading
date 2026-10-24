[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('setup', 'test', 'lint', 'sim', 'demo', 'demo-offline', 'demo-azure',
        'demo-replay', 'demo-check', 'down', 'docker-build', 'tf-validate', 'tf-plan', 'preflight')]
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
            Invoke-External $Python @('-m', 'pip', 'install', '-e', '.[dev,live,services]')
        }
        'test' { Invoke-External $Python (@('-m', 'pytest', '--cov=offloader', '--cov-report=term-missing') + $TaskArgs) }
        'lint' {
            Invoke-External $Ruff (@('check', '.') + $TaskArgs)
            Invoke-External $Ruff @('format', '--check', '.')
        }
        'sim' { Invoke-External $Python (@('offloading.py') + $TaskArgs) }
        'demo' {
            Invoke-External 'docker' @('compose', 'up', '-d', '--build', '--wait')
            Start-Process 'http://localhost:8000/console'
        }
        'demo-offline' {
            Invoke-External 'docker' @('compose', 'up', '-d', '--build', '--wait')
            Start-Process 'http://localhost:8000/console'
        }
        'demo-azure' {
            if (-not $env:AZURE_WORKER_URL) { throw 'Set AZURE_WORKER_URL to the deployed HTTPS worker URL.' }
            if (-not $env:CLOUD_API_KEY) { throw 'Set CLOUD_API_KEY in this PowerShell session for the Azure worker.' }
            $env:CLOUD_URL = $env:AZURE_WORKER_URL
            Invoke-External 'docker' @('compose', 'up', '-d', '--build', '--wait')
            Start-Process 'http://localhost:8000/console'
        }
        'demo-replay' { Invoke-External $Python @('scripts\replay.py') }
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
