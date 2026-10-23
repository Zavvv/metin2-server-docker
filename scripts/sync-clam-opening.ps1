[CmdletBinding()]
param(
    [ValidateSet('Apply', 'Verify')]
    [string]$Mode = 'Verify'
)

$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $repositoryRoot 'config\clam-opening.json'
$questPath = Join-Path $repositoryRoot 'game\quest\clam_opening.quest'
$dockerfilePath = Join-Path $repositoryRoot 'game\Dockerfile'

foreach ($path in @($configPath, $dockerfilePath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "File richiesto mancante: $path"
    }
}

$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$properties = @('stone_percent', 'empty_percent', 'white_pearl_percent', 'blue_pearl_percent', 'blood_red_pearl_percent')
$values = @{}
foreach ($property in $properties) {
    $value = $config.$property
    if ($null -eq $value -or $value -ne [math]::Floor([double]$value) -or $value -lt 0 -or $value -gt 100) {
        throw "Valore non valido per ${property}: $value"
    }
    $values[$property] = [int]$value
}
if (($values.Values | Measure-Object -Sum).Sum -ne 100) {
    throw 'Le percentuali della Clam devono sommare esattamente 100.'
}

$stoneEnd = $values.stone_percent
$emptyEnd = $stoneEnd + $values.empty_percent
$whiteEnd = $emptyEnd + $values.white_pearl_percent
$blueEnd = $whiteEnd + $values.blue_pearl_percent

$questExpected = @(
    '-- Clam item 27987: the protected game core owns the native opening odds.'
    '-- This item.use handler provides the versioned server policy without game-core sources.'
    'quest clam_opening begin'
    '    state start begin'
    '        when 27987.use begin'
    '            local r = number(1, 100)'
    '            item.remove(1)'
    ''
    "            if r <= $stoneEnd then"
    '                syschat(get_lctext("You find a simple Piece of Stone in the Clam."))'
    '                pc.give_item2(27990)'
    "            elseif r <= $emptyEnd then"
    '                syschat(get_lctext("The Clam has vanished."))'
    "            elseif r <= $whiteEnd then"
    '                syschat(get_lctext("There is a White Pearl inside the Clam."))'
    '                pc.give_item2(27992)'
    "            elseif r <= $blueEnd then"
    '                syschat(get_lctext("There is a Blue Pearl inside the Clam."))'
    '                pc.give_item2(27993)'
    '            else'
    '                syschat(get_lctext("There is a Blood-Red Pearl inside the Clam."))'
    '                pc.give_item2(27994)'
    '            end'
    '        end'
    '    end'
    'end'
) -join "`n"
$questExpected += "`n"

function Normalize-Newlines([string]$value) {
    return $value -replace "`r`n", "`n" -replace "`r", "`n"
}

if ($Mode -eq 'Apply' -and ((-not (Test-Path -LiteralPath $questPath -PathType Leaf)) -or (Normalize-Newlines (Get-Content -LiteralPath $questPath -Raw)) -ne $questExpected)) {
    [System.IO.File]::WriteAllText($questPath, $questExpected, [System.Text.UTF8Encoding]::new($false))
}
if ((-not (Test-Path -LiteralPath $questPath -PathType Leaf)) -or (Normalize-Newlines (Get-Content -LiteralPath $questPath -Raw)) -ne $questExpected) {
    throw 'La quest Clam non contiene le percentuali personalizzate. Esegui: powershell -ExecutionPolicy Bypass -File scripts\sync-clam-opening.ps1 -Mode Apply'
}

$dockerfile = [System.IO.File]::ReadAllText($dockerfilePath)
$compilePattern = '(?m)^(?<prefix>[ \t]*for q in )(?<list>.*?)(?<suffix>; do \\)$'
$matches = [regex]::Matches($dockerfile, $compilePattern)
if ($matches.Count -ne 1) {
    throw "Attesa una sola lista di compilazione quest nel Dockerfile, trovate $($matches.Count)."
}

$questNames = @($matches[0].Groups['list'].Value -split '\s+' | Where-Object { $_ })
if (($questNames | Where-Object { $_ -eq 'clam_opening' }).Count -gt 1) {
    throw 'Il Dockerfile include clam_opening più di una volta.'
}
if ($Mode -eq 'Apply' -and -not ($questNames -contains 'clam_opening')) {
    $questNames += 'clam_opening'
    $replacement = $matches[0].Groups['prefix'].Value + ($questNames -join ' ') + $matches[0].Groups['suffix'].Value
    $dockerfile = [regex]::Replace($dockerfile, $compilePattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($match) $replacement }, 1)
    [System.IO.File]::WriteAllText($dockerfilePath, $dockerfile, [System.Text.UTF8Encoding]::new($false))
    $dockerfile = [System.IO.File]::ReadAllText($dockerfilePath)
    $matches = [regex]::Matches($dockerfile, $compilePattern)
    $questNames = @($matches[0].Groups['list'].Value -split '\s+' | Where-Object { $_ })
}
if ($matches.Count -ne 1 -or ($questNames | Where-Object { $_ -eq 'clam_opening' }).Count -ne 1) {
    throw 'Il Dockerfile non compila la quest clam_opening. Esegui: powershell -ExecutionPolicy Bypass -File scripts\sync-clam-opening.ps1 -Mode Apply'
}

Write-Output "Clam opening verificato: pietra=$($values.stone_percent)% vuota=$($values.empty_percent)% bianca=$($values.white_pearl_percent)% blu=$($values.blue_pearl_percent)% rosso-sangue=$($values.blood_red_pearl_percent)%"
