# Windows PowerShell 5.1. DaneSwiata.ps1 in the zip the classic panel's
# "Dane dla klienta" page hands out (files/client_protos.py, make_zip): the
# host's world data - pack\gamedata.index and .data with the world's item and
# monster tables - installed into the client folder this script sits in.
# Never starts the game, never touches anything outside this folder, never
# writes a file the client reads before both new files have been checked and
# the client's own copies put aside.
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Action = 'install',
    [ValidateSet('auto', 'pl', 'en')][string]$Language = 'auto'
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:english = $false

function UI-Text {
    param([string]$Pl, [string]$En)
    if ($script:english) { return $En }
    return $Pl
}

function Get-ClientLanguage {
    param([string]$ClientDir)
    try {
        foreach ($line in [IO.File]::ReadAllLines((Join-Path $ClientDir 'game1.cfg'), [Text.Encoding]::Default)) {
            if ($line -match '^\s*LANGUAGE\s+(\S+)') { return $Matches[1].Trim('"').ToLowerInvariant() }
        }
    } catch { }
    return 'pl'
}

function Get-Value {
    param($Object, [string]$Name, $Default = $null)
    if ($null -ne $Object) {
        $property = $Object.PSObject.Properties[$Name]
        if ($null -ne $property) { return $property.Value }
    }
    return $Default
}

function Get-Hash {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return '' }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-PackSha {
    # client_protos.pack_sha: the two files' digests side by side, hashed.
    param([string]$Folder)
    $index = Get-Hash (Join-Path $Folder 'gamedata.index')
    $data = Get-Hash (Join-Path $Folder 'gamedata.data')
    if (-not $index -or -not $data) { return '' }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($index + $data))
        return (-join ($bytes | ForEach-Object { $_.ToString('x2') }))
    } finally { $sha.Dispose() }
}

function Assert-GameClosed {
    param([string]$ClientDir)
    $root = [IO.Path]::GetFullPath($ClientDir).TrimEnd('\') + '\'
    foreach ($process in @(Get-Process)) {
        $path = ''
        try { $path = $process.Path } catch { }
        if (($path -and $path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) -or
            (-not $path -and $process.ProcessName -like 'metin2client*')) {
            throw (UI-Text 'Gra jest uruchomiona. Zamknij ją i uruchom DaneSwiata.bat ponownie.' 'The game is running. Close it and run DaneSwiata.bat again.')
        }
    }
}

function Assert-NoLink {
    param([string]$Root, [string]$Path)
    # Neither a target nor any folder above it inside the client may redirect writes.
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $check = [IO.Path]::GetFullPath($Path)
    if (-not $check.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase) -and $check -ne $base) {
        throw (UI-Text "Ścieżka wychodzi poza folder klienta: $Path" "The path reaches outside the client folder: $Path")
    }
    while ($check.Length -ge $base.Length) {
        if ((Test-Path -LiteralPath $check) -and
            ((Get-Item -LiteralPath $check -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw (UI-Text "Dowiązanie w folderze klienta: $check" "A link in the client folder: $check")
        }
        $check = Split-Path -Parent $check
        if (-not $check) { break }
    }
}

function Copy-PackPair {
    # Both files of a pack from one folder to another, each through a sibling
    # temporary file and a move, so no reader ever sees half of one.
    param([string]$From, [string]$To, [string]$Root)
    foreach ($name in @('gamedata.index', 'gamedata.data')) {
        $target = Join-Path $To $name
        Assert-NoLink $Root $target
        $temp = $target + '.m2-world-' + [Guid]::NewGuid().ToString('N')
        try {
            Copy-Item -LiteralPath (Join-Path $From $name) -Destination $temp -Force
            Move-Item -LiteralPath $temp -Destination $target -Force
        } finally { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
    }
}

function Set-ClientPack {
    # The new pair over pack\, with the pair that was there kept in
    # world-data\previous and put back if either file fails.
    param([string]$ClientDir, [string]$From, [string]$Previous)
    $pack = Join-Path $ClientDir 'pack'
    New-Item -ItemType Directory -Path $Previous -Force | Out-Null
    Copy-PackPair -From $pack -To $Previous -Root $ClientDir
    if ((Get-PackSha $Previous) -ne (Get-PackSha $pack)) {
        throw (UI-Text 'Nie udało się zrobić kopii obecnych plików. Niczego nie podmieniono.' 'Could not back up the current files. Nothing was replaced.')
    }
    try { Copy-PackPair -From $From -To $pack -Root $ClientDir }
    catch {
        $reason = $_.Exception.Message
        try { Copy-PackPair -From $Previous -To $pack -Root $ClientDir }
        catch { throw (UI-Text "Podmiana nie powiodła się, a przywrócenie też nie. Skopiuj ręcznie pliki z $Previous do pack\. $reason" "The replacement failed and so did the rollback. Copy the files from $Previous into pack\ by hand. $reason") }
        throw (UI-Text "Podmiana nie powiodła się; przywrócono wcześniejsze pliki. $reason" "The replacement failed; the previous files are back. $reason")
    }
}

function Read-Json {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try { return ([IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8).TrimStart([char]0xFEFF) | ConvertFrom-Json) }
    catch { return $null }
}

function Save-Json {
    param([string]$Path, $Value)
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new($false))
}

function Invoke-WorldData {
    param([string]$ClientDir, [string]$Mode)
    $ClientDir = [IO.Path]::GetFullPath($ClientDir).TrimEnd('\')
    $script:english = if ($Language -eq 'auto') { (Get-ClientLanguage $ClientDir) -ne 'pl' } else { $Language -eq 'en' }
    $pack = Join-Path $ClientDir 'pack'
    $world = Join-Path $ClientDir 'world-data'
    $stock = Join-Path $world 'stock'
    if (-not (Test-Path -LiteralPath (Join-Path $pack 'gamedata.index') -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $pack 'gamedata.data') -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $ClientDir 'metin2client.exe') -PathType Leaf)) {
        throw (UI-Text 'To nie jest folder klienta gry. Rozpakuj całe archiwum do folderu, w którym jest metin2client.exe, i uruchom DaneSwiata.bat stamtąd.' 'This is not the game client''s folder. Extract the whole archive into the folder with metin2client.exe and run DaneSwiata.bat from there.')
    }
    Assert-GameClosed $ClientDir
    $lockPath = Join-Path $ClientDir '.world-data.lock'
    Assert-NoLink $ClientDir $lockPath
    $lock = $null
    try {
        try { $lock = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
        catch { throw (UI-Text 'Inna instalacja już działa albo folder nie pozwala na zapis.' 'Another installation is running, or this folder is not writable.') }
        $current = Get-PackSha $pack
        $installed = Read-Json (Join-Path $world 'installed.json')
        $stockSha = Get-PackSha $stock
        if ($Mode -in @('restore', 'przywroc', 'przywróć')) {
            if (-not $stockSha) {
                Write-Host (UI-Text 'Nie ma kopii oryginalnych plików - klient ma swoje własne.' 'There is no copy of the original files - the client has its own.')
                return
            }
            if ($current -eq $stockSha) {
                Write-Host (UI-Text 'Klient ma już oryginalne pliki.' 'The client already has the original files.')
                return
            }
            if (-not $installed -or [string](Get-Value $installed 'out' '') -ne $current) {
                throw (UI-Text 'Pliki klienta to nie dane świata wgrane tym programem (np. klient był aktualizowany). Niczego nie zmieniono.' 'The client''s files are not the world data this program installed (the client was updated, for example). Nothing was changed.')
            }
            Set-ClientPack -ClientDir $ClientDir -From $stock -Previous (Join-Path $world 'previous')
            Remove-Item -LiteralPath (Join-Path $world 'installed.json') -Force -ErrorAction SilentlyContinue
            Write-Host (UI-Text 'Przywrócono oryginalne pliki klienta.' 'The client''s original files are back.')
            return
        }
        if ($Mode -ne 'install') { throw (UI-Text "Nieznane polecenie: $Mode (dozwolone: przywroc)" "Unknown command: $Mode (allowed: restore)") }
        $manifest = Read-Json (Join-Path $world 'world-data.json')
        if (-not $manifest -or [string](Get-Value $manifest 'kind' '') -ne 'metin2-world-data' -or [int](Get-Value $manifest 'format' 0) -ne 1) {
            throw (UI-Text 'Brak world-data\world-data.json albo to nie jest paczka danych świata. Rozpakuj całe archiwum jeszcze raz.' 'world-data\world-data.json is missing or this is not a world data package. Extract the whole archive again.')
        }
        $out = Get-Value $manifest 'out'
        $base = Get-Value $manifest 'base'
        $clientVersion = [string](Get-Value $manifest 'client_version' '?')
        if ((Get-Hash (Join-Path $world 'gamedata.index')) -ne [string](Get-Value $out 'index_sha256' '') -or
            (Get-Hash (Join-Path $world 'gamedata.data')) -ne [string](Get-Value $out 'data_sha256' '')) {
            throw (UI-Text 'Pliki w world-data są uszkodzone albo niepełne. Pobierz paczkę z panelu jeszcze raz.' 'The files in world-data are damaged or incomplete. Download the package from the panel again.')
        }
        $outSha = [string](Get-Value $out 'sha256' '')
        $baseSha = [string](Get-Value $base 'sha256' '')
        if ($current -eq $outSha) {
            Write-Host (UI-Text 'Te dane świata są już wgrane. Możesz grać.' 'This world data is already installed. You can play.')
            return
        }
        if ($current -eq $baseSha) {
            # The client's own files, as the package was made for them: kept
            # aside once, for "przywroc" and for the next package.
            New-Item -ItemType Directory -Path $stock -Force | Out-Null
            if ($stockSha -ne $current) { Copy-PackPair -From $pack -To $stock -Root $ClientDir }
            if ((Get-PackSha $stock) -ne $current) { throw (UI-Text 'Nie udało się zachować oryginalnych plików. Niczego nie podmieniono.' 'Could not keep the original files. Nothing was replaced.') }
        }
        elseif (-not ($stockSha -eq $baseSha -and $installed -and [string](Get-Value $installed 'out' '') -eq $current)) {
            throw ((UI-Text 'Twój klient ma inne pliki gry (pack\gamedata) niż te, dla których gospodarz przygotował paczkę (klient {0}). Zaktualizuj klienta przez Aktualizuj.bat i uruchom DaneSwiata.bat ponownie. Jeśli nadal się nie zgadza, gospodarz musi zaktualizować serwer i pobrać nową paczkę z panelu. Niczego nie zmieniono.' 'Your client''s game files (pack\gamedata) are not the ones the host made this package for (client {0}). Update the client with Aktualizuj.bat and run DaneSwiata.bat again. If it still does not match, the host has to update the server and download a new package from the panel. Nothing was changed.') -f $clientVersion)
        }
        Set-ClientPack -ClientDir $ClientDir -From $world -Previous (Join-Path $world 'previous')
        if ((Get-PackSha $pack) -ne $outSha) { throw (UI-Text 'Po podmianie pliki się nie zgadzają. Uruchom DaneSwiata.bat przywroc.' 'The files do not match after the replacement. Run DaneSwiata.bat restore.') }
        Save-Json (Join-Path $world 'installed.json') ([ordered]@{ out = $outSha; base = $baseSha; client_version = $clientVersion; installed_at = (Get-Date).ToString('s') })
        Write-Host (UI-Text 'Gotowe: klient ma dane przedmiotów i potworów tego świata. Możesz grać. (Powrót do oryginału: DaneSwiata.bat przywroc)' 'Done: the client has this world''s item and monster data. You can play. (Back to the original: DaneSwiata.bat restore)')
    } finally {
        if ($lock) { $lock.Dispose() }
        Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    try { Invoke-WorldData -ClientDir $PSScriptRoot -Mode $Action.ToLowerInvariant() }
    catch { Write-Host ((UI-Text 'Nie udało się: {0}' 'It did not work: {0}') -f $_.Exception.Message) -ForegroundColor Red; exit 1 }
}
