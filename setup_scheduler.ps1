# GamesMap Studio Career Job Monitor - Windows Task Scheduler Setup
# Schedules career_monitor.py to run automatically at user-configured check times

param (
    [string[]]$Times = @(),
    [switch]$Unregister = $false
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$pythonPath = (Get-Command python.exe -ErrorAction SilentlyContinue).Source

if (-not $pythonPath) {
    Write-Error "Python was not found in PATH. Please install Python or specify the full path."
    exit 1
}

$pythonwPath = Join-Path (Split-Path -Parent $pythonPath) "pythonw.exe"
$executable = if (Test-Path $pythonwPath) { $pythonwPath } else { $pythonPath }

$scriptPath = Join-Path $scriptDir "career_monitor.py"
$taskName = "GamesMap_Career_JobMonitor"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "[OK] Task '$taskName' removed from Windows Task Scheduler." -ForegroundColor Yellow
    exit 0
}

# If times were not passed via CLI parameters, load from config.json
if ($Times.Count -eq 0) {
    $configPath = Join-Path $scriptDir "config.json"
    if (-not (Test-Path $configPath)) {
        $configPath = Join-Path $scriptDir "config.example.json"
    }
    if (Test-Path $configPath) {
        try {
            $config = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($config.schedule -and $config.schedule.enabled -eq $false) {
                Write-Host "[!] Schedule is marked as disabled in config.json." -ForegroundColor Yellow
                Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
                exit 0
            }
            if ($config.schedule -and $config.schedule.times) {
                $Times = @($config.schedule.times)
            }
        } catch {
            Write-Warning "Could not parse config schedule times: $_"
        }
    }
}

# Default fallback if no times are specified
if ($Times.Count -eq 0) {
    $Times = @("09:00", "13:00", "18:00")
}

# Flatten and normalize comma-separated strings or arrays
$flattenedTimes = @()
foreach ($item in $Times) {
    if ($item) {
        $parts = ("$item").Split(",")
        foreach ($p in $parts) {
            $t = $p.Trim()
            if ($t -and -not $flattenedTimes.Contains($t)) {
                $flattenedTimes += $t
            }
        }
    }
}
$Times = $flattenedTimes

Write-Host "Setting up Scheduled Task: $taskName" -ForegroundColor Cyan
Write-Host "Target Script:     $scriptPath"
Write-Host "Python Executable: $executable"
Write-Host "Scheduled Times:   $($Times -join ', ')"

$triggers = @()
$registeredTimesDisplay = @()

foreach ($timeStr in $Times) {
    $cleanTime = ("$timeStr").Trim()
    if ($cleanTime) {
        try {
            # Normalize HH:MM to 24h trigger
            $trigger = New-ScheduledTaskTrigger -Daily -At $cleanTime
            $triggers += $trigger
            
            # Format nicely for display (e.g. 13:00 -> 1:00 PM)
            try {
                $dt = [datetime]::ParseExact($cleanTime, "HH:mm", [System.Globalization.CultureInfo]::InvariantCulture)
                $registeredTimesDisplay += "$cleanTime ($($dt.ToString('hh:mm tt')))"
            } catch {
                $registeredTimesDisplay += "$cleanTime"
            }
        } catch {
            Write-Warning "Failed to create trigger for time: '$cleanTime' ($($_))"
        }
    }
}

if ($triggers.Count -eq 0) {
    Write-Error "No valid triggers could be created from the provided times."
    exit 1
}

# Action to execute
$action = New-ScheduledTaskAction -Execute $executable -Argument "`"$scriptPath`"" -WorkingDirectory $scriptDir

# Settings: Allow battery run, wake / start when available
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# Register or update task
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $taskName -Trigger $triggers -Action $action -Settings $settings -Description "Checks UK Game Studio career pages for new Technical Artist & Game Dev positions ($($Times -join ', '))" -Force

Write-Host "`n[OK] Task '$taskName' successfully registered with $($triggers.Count) daily trigger(s)!" -ForegroundColor Green
Write-Host "Daily Check Schedule:"
foreach ($t in $registeredTimesDisplay) {
    Write-Host "  - $t" -ForegroundColor White
}
Write-Host "`nYou can test-run the task manually at any time with:"
Write-Host "  Start-ScheduledTask -TaskName '$taskName'" -ForegroundColor Yellow

