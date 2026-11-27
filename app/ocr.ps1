param([Parameter(Mandatory=$true)][string]$Folder)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$memoryStream = [Windows.Storage.Streams.InMemoryRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime]
$writerType = [Windows.Storage.Streams.DataWriter,Windows.Storage.Streams,ContentType=WindowsRuntime]
$decoder = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$bitmap = [Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$result = [Windows.Media.Ocr.OcrResult,Windows.Foundation,ContentType=WindowsRuntime]
$engineType = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$languageType = [Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1
} | Select-Object -First 1
function Await-Result($operation, [type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation))
    $task.GetAwaiter().GetResult()
}
$engine = $engineType::TryCreateFromLanguage($languageType::new('ko-KR'))
if (!$engine) { $engine = $engineType::TryCreateFromUserProfileLanguages() }
if (!$engine) { throw 'No Windows OCR language is available.' }
Get-ChildItem -LiteralPath $Folder -Filter '*.jpg' -File | Sort-Object Name | ForEach-Object {
    $inputStream = $memoryStream::new()
    try {
        $writer = $writerType::new($inputStream)
        try {
            $writer.WriteBytes([System.IO.File]::ReadAllBytes($_.FullName))
            $null = Await-Result ($writer.StoreAsync()) ([uint32])
            $null = $writer.DetachStream()
        }
        finally { $writer.Dispose() }
        $inputStream.Seek(0)
        $imageDecoder = Await-Result ($decoder::CreateAsync($inputStream)) $decoder
        $pixels = Await-Result ($imageDecoder.GetSoftwareBitmapAsync()) $bitmap
        try {
            $ocr = Await-Result ($engine.RecognizeAsync($pixels)) $result
            $lines = @($ocr.Lines | ForEach-Object {
                $words = @($_.Words)
                $top = if ($words.Count) { ($words | ForEach-Object {$_.BoundingRect.Y} | Measure-Object -Maximum).Maximum } else { 0 }
                @{text=$_.Text; y=($top / [Math]::Max(1,$imageDecoder.PixelHeight))}
            })
            @{file=$_.BaseName; lines=$lines} | ConvertTo-Json -Compress -Depth 4
        }
        finally { $pixels.Dispose() }
    }
    finally { $inputStream.Dispose() }
}
