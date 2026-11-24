# Follow a dsd phase live: what CodeBuddy says and which tools it runs.
# pwsh ./watch.ps1 <workdir>/.dsd/<job>/<phase>.log
# Without -Log, find the newest dsd log under -Root (default: current directory).
param([string]$Log, [string]$Root = (Get-Location).Path)
if (-not $Log) {
	$patterns = @((Join-Path $Root '.dsd\*\*.log'), (Join-Path $Root '*\.dsd\*\*.log'))
	$Log = Get-ChildItem -Path $patterns -File -ErrorAction SilentlyContinue |
		Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $Log -or -not (Test-Path $Log)) { Write-Host "no log found"; exit 1 }
Write-Host "== $Log (Ctrl+C to stop)" -ForegroundColor Cyan

function Short([string]$s, [int]$n = 160) {
	$s = ($s -replace '\s+', ' ').Trim()
	if ($s.Length -gt $n) { $s.Substring(0, $n) + ' …' } else { $s }
}

Get-Content -LiteralPath $Log -Wait -Encoding UTF8 | ForEach-Object {
	try { $r = $_ | ConvertFrom-Json -ErrorAction Stop } catch { return }
	$t = Get-Date -Format HH:mm:ss
	if ($r.type -eq 'assistant' -and $r.message.content) {
		foreach ($c in $r.message.content) {
			if ($c.type -eq 'text' -and $c.text.Trim()) {
				Write-Host "$t 说: " -NoNewline -ForegroundColor Green; Write-Host (Short $c.text 400)
			} elseif ($c.type -eq 'tool_use') {
				$i = $c.input
				$arg = if ($i.command) { $i.command } elseif ($i.file_path) { $i.file_path } elseif ($i.path) { $i.path } elseif ($i.pattern) { $i.pattern } else { ($i | ConvertTo-Json -Compress -Depth 3) }
				Write-Host "$t $($c.name): " -NoNewline -ForegroundColor Yellow; Write-Host (Short "$arg")
			}
		}
	} elseif ($r.type -eq 'user' -and $r.message.content) {
		foreach ($c in $r.message.content) {
			if ($c.type -eq 'tool_result' -and $c.is_error) {
				Write-Host "$t 工具报错: " -NoNewline -ForegroundColor Red; Write-Host (Short "$($c.content)")
			}
		}
	} elseif ($r.type -eq 'result') {
		Write-Host "$t == 本阶段结束 ($($r.subtype))" -ForegroundColor Cyan
	}
}
