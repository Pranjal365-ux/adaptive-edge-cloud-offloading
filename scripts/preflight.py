"""Read-only checks for local tooling and Azure prerequisites; never logs in or prints IDs."""

from __future__ import annotations

import shutil
import subprocess

PROVIDERS = (
    "Microsoft.App",
    "Microsoft.OperationalInsights",
    "Microsoft.KeyVault",
    "Microsoft.Consumption",
    "Microsoft.Insights",
    "Microsoft.Storage",
)


def run(args: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=20, check=False)
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


def check_command(label: str, command: str, args: list[str]) -> None:
    if not shutil.which(command):
        print(f"BLOCKED {label}: {command} not found on PATH")
        return
    code, output = run([command, *args])
    print(f"{'OK' if code == 0 else 'BLOCKED'} {label}" + (f": {output}" if output else ""))


def main() -> int:
    check_command("Docker engine", "docker", ["info", "--format", "{{.ServerVersion}}"])
    check_command("Terraform CLI", "terraform", ["version", "-json"])
    check_command("Azure CLI", "az", ["version", "--output", "none"])
    if not shutil.which("az"):
        print("BLOCKED Azure authentication: install Azure CLI and run az login")
        return 0
    code, _ = run(["az", "account", "show", "--query", "id", "--output", "tsv"])
    if code:
        print(
            "BLOCKED Azure authentication: run az login, then select a subscription "
            "with az account set"
        )
        return 0
    print("OK Azure authentication: a subscription is selected (ID intentionally not printed)")
    for provider in PROVIDERS:
        code, state = run(
            [
                "az",
                "provider",
                "show",
                "--namespace",
                provider,
                "--query",
                "registrationState",
                "--output",
                "tsv",
            ]
        )
        if code:
            print(
                f"BLOCKED provider {provider}: check subscription permissions and run "
                f"az provider register --namespace {provider}"
            )
        elif state.lower() != "registered":
            print(
                f"BLOCKED provider {provider}: state is {state or 'unknown'}; run "
                f"az provider register --namespace {provider}"
            )
        else:
            print(f"OK provider {provider}: registered")
    print("Terraform init/validate are local checks; this preflight does not create resources.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
