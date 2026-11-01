# Reads every timesheet photo with Windows' own OCR engine and writes what it finds to a JSONL file.
#
# Nothing is installed: Windows.Media.Ocr ships with Windows 10/11. The photos are handwritten, so the
# reading is rough - but each word comes back with a box, and the "Time out" column is the right-hand
# edge of the page, so the times can be picked out by position and the noise averaged away over hundreds
# of sheets. ocrclose.py turns the JSONL into a closing time per venue.
#
#   powershell -ExecutionPolicy Bypass -File ocrscan.ps1 [-Out <file>] [-Max <n>] [-Since 2025]
#
# Read-only: it opens the photos and writes one file of its own. It never touches the sheets.
param(
    [string]$Out = "$PSScriptRoot\ocr\words.jsonl",
    [int]$Max = 4000,
    [int]$Since = 2025
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path (Split-Path $Out) | Out-Null

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($task, $type) {
    $m = $asTaskGeneric.MakeGenericMethod($type)
    $t = $m.Invoke($null, @($task))
    $t.Wait(-1) | Out-Null
    $t.Result
}
[void][Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
[void][Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime]
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if (-not $engine) { Write-Error "no OCR engine on this machine"; exit 1 }
Write-Host "OCR engine: $($engine.RecognizerLanguage.DisplayName)"

# every timesheet folder we can see, newest first
$roots = @("$env:USERPROFILE\Desktop", "$env:USERPROFILE\Desktop\Important DATA\Timesheets")
$folders = @()
foreach ($root in $roots) {
    if (Test-Path $root) {
        $folders += Get-ChildItem $root -Directory -Recurse -Depth 1 -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^\s*time\s*sheets?' }
    }
}
$folders = $folders | Where-Object { $_.Name -match '(\d{2,4})\s*$' -and
    [int]($matches[1] -replace '^(\d{2})$', '20$1') -ge $Since } | Sort-Object Name -Descending
Write-Host "$($folders.Count) folders to read"

$done = 0
$started = Get-Date
$writer = [System.IO.StreamWriter]::new($Out, $false, [System.Text.UTF8Encoding]::new($false))
try {
    foreach ($folder in $folders) {
        foreach ($img in Get-ChildItem $folder.FullName -File -ErrorAction SilentlyContinue) {
            if ($img.Extension -notmatch '^\.(jpg|jpeg|png|bmp|tif|tiff)$') { continue }
            if ($done -ge $Max) { break }
            try {
                $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($img.FullName)) ([Windows.Storage.StorageFile])
                $stream = Await ($file.OpenAsync(0)) ([Windows.Storage.Streams.IRandomAccessStream])
                $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
                $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
                $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
                $w = $decoder.PixelWidth; $h = $decoder.PixelHeight
                $words = @()
                foreach ($lineItem in $result.Lines) {
                    foreach ($word in $lineItem.Words) {
                        $r = $word.BoundingRect
                        $words += @{
                            t = $word.Text
                            x = [math]::Round(($r.X + $r.Width / 2) / $w, 4)   # centre, as a fraction
                            y = [math]::Round(($r.Y + $r.Height / 2) / $h, 4)
                        }
                    }
                }
                $row = @{ folder = $folder.Name; file = $img.Name; w = $w; h = $h; words = $words }
                $writer.WriteLine(($row | ConvertTo-Json -Compress -Depth 5))
                $stream.Dispose()
            }
            catch {
                $writer.WriteLine((@{ folder = $folder.Name; file = $img.Name; error = "$($_.Exception.Message)" } |
                        ConvertTo-Json -Compress))
            }
            $done++
            if ($done % 25 -eq 0) {
                $rate = $done / [math]::Max(1, (Get-Date).Subtract($started).TotalSeconds)
                Write-Host ("  {0} sheets read, {1:N1}/s" -f $done, $rate)
                $writer.Flush()
            }
        }
        if ($done -ge $Max) { break }
    }
}
finally { $writer.Close() }
Write-Host ("done: {0} sheets in {1:N0}s -> {2}" -f $done, (Get-Date).Subtract($started).TotalSeconds, $Out)
