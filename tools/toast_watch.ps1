<#
.SYNOPSIS
    Windows-notification watcher for the netrunner bot -- runs independent of any
    Claude Code session, so alerts keep firing after that session ends (usage
    limit, closed window, crash) until the user is back to look.

.DESCRIPTION
    Two sources, same job as the two `Monitor` tasks a Claude session normally
    arms:
      1. Tails logs/netrunner.log for the same patterns the log Monitor used --
         badge reads, gate decisions, episode switch/restore, recovery escalation,
         crashes.
      2. Runs tools/screen_watch.py as a child process and forwards its SCREEN
         stuck/cleared/emulator-gone lines.
    Each matching line becomes one Windows toast notification (native
    Windows.UI.Notifications API -- no module install required). Notifications
    land in Action Center even if Focus Assist/DND is on; DND only suppresses
    the on-screen banner, not delivery, so nothing is lost either way.

.NOTES
    Start this from Task Scheduler ("At log on", no user session required) or
    manually with:
        powershell -ExecutionPolicy Bypass -File tools\toast_watch.ps1
    Stop with Ctrl+C, or find and kill the powershell.exe process running it.

    Deliberately NOT a Claude Code `Monitor` task -- those die with the session
    that armed them. This is a plain background process outliving any single
    Claude session, which is the whole point.
#>

param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$Device = "127.0.0.1:5555",
    [int]$ScreenStuckAfter = 240
)

$ErrorActionPreference = "Continue"
$logPath = Join-Path $RepoRoot "logs\netrunner.log"
$appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'

[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

function Send-Toast {
    param([string]$Title, [string]$Body)
    try {
        $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
            [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
        $textNodes = $xml.GetElementsByTagName("text")
        $textNodes.Item(0).AppendChild($xml.CreateTextNode($Title)) | Out-Null
        $textNodes.Item(1).AppendChild($xml.CreateTextNode($Body)) | Out-Null
        $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
    } catch {
        # A failed toast must not kill the watcher -- write to a fallback file
        # instead so the alert survives even if the Toast API itself breaks.
        $fallback = Join-Path $RepoRoot "logs\toast_watch_failures.log"
        "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  TOAST FAILED: $Title | $Body | $($_.Exception.Message)" |
            Add-Content -Path $fallback -Encoding utf8
    }
}

# Same alternation the log Monitor used. Anchored to avoid matching the
# injected 'X '-prefixed selftest lines other sessions may have left behind.
$logPattern = 'remember_lives_waiting:|lives_under:|remember_episode:|restore_episode:|' +
              'errand: (starting|Episode|.* finished)|switch to Episode|could NOT restore|' +
              'Episode [0-9] restored|transition (open_mailbox|mailbox_base)|confirm_loop -> (done|close_mailbox)|' +
              '-> mailbox_count_gate|-> exit_dismiss_exitgame|-> exit_to_home_verify|-> recover_unknown_backspam|' +
              '-> recover_login|recover_pick ->|restart_app:|require_foreground:|-> recover_stuck|-> recover_unknown\b|' +
              'ERROR|CRITICAL|Traceback|Unhandled|reached max_cycles|no progress'

# Only these are worth a toast -- the rest (badge reads, routine transitions)
# would spam Action Center all night. Mirrors what actually warranted a
# response during live monitoring sessions.
$alertPattern = 'switch to Episode \d+ failed|could NOT restore|no progress|ERROR|CRITICAL|Traceback|' +
                 'reached max_cycles|-> recover_unknown_restart|restart_app:'

Write-Host "[toast_watch] watching $logPath"
Write-Host "[toast_watch] screen_watch stuck-after: ${ScreenStuckAfter}s"
Send-Toast "netrunner watcher started" "Log + screen watcher running independent of any Claude session."

# --- log tailer (background runspace) ---------------------------------------
$logJob = Start-Job -ScriptBlock {
    param($LogPath, $Pattern, $AlertPattern)
    if (-not (Test-Path $LogPath)) {
        Start-Sleep -Seconds 2
    }
    Get-Content -Path $LogPath -Tail 0 -Wait -Encoding utf8 |
        Where-Object { $_ -notmatch '^X ' -and $_ -match $Pattern } |
        ForEach-Object {
            $isAlert = $_ -match $AlertPattern
            [PSCustomObject]@{ Line = $_; Alert = $isAlert }
        }
} -ArgumentList $logPath, $logPattern, $alertPattern

# --- screen watcher (child process) ------------------------------------------
$screenWatchPy = Join-Path $RepoRoot "tools\screen_watch.py"
$pyExe = "C:\Users\kongp\AppData\Local\Microsoft\WindowsApps\python.exe"
# -Environment is a PowerShell 7+ Start-Process parameter; this box runs
# Windows PowerShell 5.1, so set the child's env var the compatible way
# instead (still scoped to this process, inherited by the child on launch).
$env:PYTHONIOENCODING = "utf-8"
$screenProc = Start-Process -FilePath $pyExe `
    -ArgumentList @($screenWatchPy, "--device", $Device, "--stuck-after", $ScreenStuckAfter) `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput (Join-Path $RepoRoot "logs\toast_watch_screen.out") `
    -RedirectStandardError (Join-Path $RepoRoot "logs\toast_watch_screen.err") `
    -PassThru -WindowStyle Hidden

Write-Host "[toast_watch] screen_watch.py pid=$($screenProc.Id)"

$screenOutPath = Join-Path $RepoRoot "logs\toast_watch_screen.out"
$screenReadPos = 0

try {
    while ($true) {
        # log events
        $results = Receive-Job -Job $logJob -ErrorAction SilentlyContinue
        foreach ($r in $results) {
            $title = if ($r.Alert) { "netrunner ALERT" } else { "netrunner" }
            Send-Toast $title $r.Line.Substring([Math]::Max(0, $r.Line.Length - 200))
        }

        # screen events -- poll the redirected stdout file for new lines
        if (Test-Path $screenOutPath) {
            $stream = [System.IO.File]::Open($screenOutPath, 'Open', 'Read', 'ReadWrite')
            $stream.Seek($screenReadPos, 'Begin') | Out-Null
            $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
            while (-not $reader.EndOfStream) {
                $line = $reader.ReadLine()
                if ($line -match '^SCREEN') {
                    Send-Toast "netrunner ALERT" $line
                }
            }
            $screenReadPos = $stream.Position
            $reader.Close()
            $stream.Close()
        }

        if ($screenProc.HasExited) {
            Send-Toast "netrunner ALERT" "screen_watch.py exited unexpectedly (code $($screenProc.ExitCode)) -- screen monitoring stopped"
            break
        }
        if ($logJob.State -eq 'Failed') {
            Send-Toast "netrunner ALERT" "log watcher job failed -- log monitoring stopped"
            break
        }

        Start-Sleep -Seconds 2
    }
} finally {
    Stop-Job -Job $logJob -ErrorAction SilentlyContinue
    Remove-Job -Job $logJob -Force -ErrorAction SilentlyContinue
    if (-not $screenProc.HasExited) { Stop-Process -Id $screenProc.Id -Force -ErrorAction SilentlyContinue }
}
