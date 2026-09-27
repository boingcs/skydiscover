param(
    [int]$Iterations = 20,
    [string]$RunDir = ".skydiscover\verus-db-windows-planned",
    [string]$Verus = $env:VERUS,
    [string]$Z3 = $env:VERUS_Z3_PATH,
    [string]$Codex = "codex",
    [string]$CodexHome = (Join-Path $PSScriptRoot '..\..\..\..\.skydiscover\codex-home'),
    [string]$Prompt = "$PSScriptRoot\prompt.md",
    [string]$PlannerPrompt = "$PSScriptRoot\planner_prompt.md",
    [string]$Model = "gpt-5.6-sol",
    [ValidateSet("low", "medium", "high", "xhigh", "max", "ultra")]
    [string]$ReasoningEffort,
    # One attempt per agent by default: failures are recorded and the
    # controller proceeds without reconnecting to the same agent.
    [int]$PlannerRetries = 1,
    [int]$CoderRetries = 1,
    [int]$AgentTimeout = 3600,
    [int]$VerificationTimeout = 240,
    [switch]$Fresh,
    [switch]$KeepGoing,
    [switch]$KeepRegressions,
    [switch]$VerifyOnly,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Some Windows installations expose Codex only through a versioned directory
# under the local app installation and do not add that directory to PATH.
# Resolve the newest installed CLI before passing it to the Python controller.
if ($Codex -eq "codex") {
    $codexCommand = Get-Command codex -ErrorAction SilentlyContinue
    if ($codexCommand) {
        $Codex = $codexCommand.Source
    } else {
        $codexRoot = Join-Path $env:LOCALAPPDATA "OpenAI\Codex\bin"
        $codexInstalled = Get-ChildItem -LiteralPath $codexRoot -Directory `
            -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.FullName "codex.exe" } |
            Where-Object { Test-Path -LiteralPath $_ } |
            Sort-Object { (Get-Item -LiteralPath $_).LastWriteTime } -Descending |
            Select-Object -First 1
        if ($codexInstalled) {
            $Codex = $codexInstalled
        }
    }
}

$arguments = @(
    "$PSScriptRoot\run_windows.py",
    "--iterations", $Iterations,
    "--run-dir", $RunDir,
    "--codex", $Codex,
    "--prompt", $Prompt,
    "--planner-prompt", $PlannerPrompt,
    "--planner-retries", $PlannerRetries,
    "--coder-retries", $CoderRetries,
    "--agent-timeout", $AgentTimeout,
    "--verification-timeout", $VerificationTimeout
)
if ($Verus) { $arguments += @("--verus", $Verus) }
if ($Z3) { $arguments += @("--z3", $Z3) }
if ($Model) { $arguments += @("--model", $Model) }
if ($ReasoningEffort) { $arguments += @("--reasoning-effort", $ReasoningEffort) }
if ($CodexHome) { $arguments += @("--codex-home", $CodexHome) }
if ($Fresh) { $arguments += "--fresh" }
if ($KeepGoing) { $arguments += "--keep-going" }
if ($KeepRegressions) { $arguments += "--keep-regressions" }
if ($VerifyOnly) { $arguments += "--verify-only" }
if ($DryRun) { $arguments += "--dry-run" }

python @arguments
exit $LASTEXITCODE
