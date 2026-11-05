param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null=[Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null=[Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType=WindowsRuntime]
$null=[Windows.Data.Pdf.PdfPageRenderOptions, Windows.Data.Pdf, ContentType=WindowsRuntime]
$null=[Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.BitmapPixelFormat, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.BitmapAlphaMode, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime]
$methods=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 }
$generic=$methods | Where-Object { $_.IsGenericMethod -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
$action=$methods | Where-Object { -not $_.IsGenericMethod -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } | Select-Object -First 1
function Await-Result($op,[Type]$type) { $generic.MakeGenericMethod($type).Invoke($null,@($op)).GetAwaiter().GetResult() }
function Await-Action($op) { $null=$action.Invoke($null,@($op)).GetAwaiter().GetResult() }
$languages=@([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages)
if($languages.Count -eq 0) { throw 'No OCR language installed' }
$language=$languages | Where-Object { $_.LanguageTag -match '^zh' } | Select-Object -First 1
if(-not $language) { $language=$languages[0] }
$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
$file=Await-Result ([Windows.Storage.StorageFile]::GetFileFromPathAsync([IO.Path]::GetFullPath($Path))) ([Windows.Storage.StorageFile])
$pdf=Await-Result ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
if($pdf.PageCount -eq 0 -or $pdf.PageCount -gt 50) { throw 'PDF OCR supports 1 to 50 pages' }
$lines=@()
$recognized=0
for($index=0;$index -lt $pdf.PageCount;$index++) {
    $page=$pdf.GetPage([uint32]$index)
    $stream=[Windows.Storage.Streams.InMemoryRandomAccessStream]::new()
    try {
        $options=[Windows.Data.Pdf.PdfPageRenderOptions]::new(); $options.DestinationWidth=1800
        Await-Action ($page.RenderToStreamAsync($stream,$options))
        $decoder=Await-Result ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap=Await-Result ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        try {
            $image=[Windows.Graphics.Imaging.SoftwareBitmap]::Convert($bitmap,[Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,[Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied)
            try {
                $result=Await-Result ($engine.RecognizeAsync($image)) ([Windows.Media.Ocr.OcrResult])
                if($result.Text.Trim()) { $recognized++; $lines+=('[Page '+($index+1)+'] '+$result.Text) }
                else { $lines+=('[Page '+($index+1)+'] [No text recognized; review required]') }
            }
            finally { $image.Dispose() }
        } finally { $bitmap.Dispose() }
    } finally { $stream.Dispose(); $page.Dispose() }
}
if($recognized -eq 0) { throw 'No text recognized in PDF' }
@{text=($lines -join "`n");language=$language.LanguageTag} | ConvertTo-Json -Compress
