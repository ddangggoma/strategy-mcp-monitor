# desktop/icons/make-icon.ps1 — draws icon.ico (16, 32, 48, 256; PNG frames). Run once; the .ico is committed.
Add-Type -AssemblyName System.Drawing
$sizes = 16, 32, 48, 256
$frames = foreach ($s in $sizes) {
    $bmp = New-Object System.Drawing.Bitmap $s, $s
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear([System.Drawing.Color]::Transparent)
    $g.FillEllipse((New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 37, 99, 235))), 0, 0, $s - 1, $s - 1)
    $pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::White), ([single][Math]::Max(1, $s / 10))
    $m = [single]($s * 0.28)
    $pts = [System.Drawing.PointF[]]@(
        (New-Object System.Drawing.PointF $m, ([single]$s - $m)), (New-Object System.Drawing.PointF $m, $m),
        (New-Object System.Drawing.PointF ([single]($s / 2)), ([single]($s * 0.55))),
        (New-Object System.Drawing.PointF ([single]$s - $m), $m), (New-Object System.Drawing.PointF ([single]$s - $m), ([single]$s - $m)))
    $g.DrawLines($pen, $pts)
    $g.Dispose()
    $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
    , $ms.ToArray()
}
$out = New-Object System.IO.MemoryStream
$w = New-Object System.IO.BinaryWriter $out
$w.Write([uint16]0); $w.Write([uint16]1); $w.Write([uint16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $s = $sizes[$i]; $len = $frames[$i].Length
    $w.Write([byte]($s % 256)); $w.Write([byte]($s % 256)); $w.Write([byte]0); $w.Write([byte]0)
    $w.Write([uint16]1); $w.Write([uint16]32); $w.Write([uint32]$len); $w.Write([uint32]$offset)
    $offset += $len
}
foreach ($f in $frames) { $w.Write($f) }
[System.IO.File]::WriteAllBytes((Join-Path $PSScriptRoot "icon.ico"), $out.ToArray())
