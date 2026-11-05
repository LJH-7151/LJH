param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
$null = [Windows.Storage.FileAccessMode, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapPixelFormat, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapAlphaMode, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime]
$converter = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
function Receive-WinRt($Operation, [Type]$Type) {
    $task = $converter.MakeGenericMethod($Type).Invoke($null, @($Operation))
    $task.GetAwaiter().GetResult()
}
$languages = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages)
if ($languages.Count -eq 0) { throw 'No OCR language installed' }
$language = $languages | Where-Object { $_.LanguageTag -match '^zh' } | Select-Object -First 1
if (-not $language) { $language = $languages[0] }
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
$file = Receive-WinRt ([Windows.Storage.StorageFile]::GetFileFromPathAsync([IO.Path]::GetFullPath($Path))) ([Windows.Storage.StorageFile])
$stream = Receive-WinRt ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
try {
    $decoder = Receive-WinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Receive-WinRt ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    try {
        if ($bitmap.PixelWidth -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension -or $bitmap.PixelHeight -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension) { throw 'Image dimensions exceed OCR limit' }
        $image = [Windows.Graphics.Imaging.SoftwareBitmap]::Convert($bitmap,[Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,[Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied)
        try {
            $result = Receive-WinRt ($engine.RecognizeAsync($image)) ([Windows.Media.Ocr.OcrResult])
            @{text=$result.Text; language=$language.LanguageTag} | ConvertTo-Json -Compress
        } finally { $image.Dispose() }
    } finally { $bitmap.Dispose() }
} finally { $stream.Dispose() }
