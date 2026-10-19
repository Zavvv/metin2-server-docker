[CmdletBinding()]
param(
    [ValidateSet('Apply', 'Verify')]
    [string]$Mode = 'Verify'
)

$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $repositoryRoot 'config\dragon-soul-refine.json'
$dockerfilePath = Join-Path $repositoryRoot 'game\Dockerfile'

if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    throw "Configurazione mancante: $configPath"
}
if (-not (Test-Path -LiteralPath $dockerfilePath -PathType Leaf)) {
    throw "Dockerfile mancante: $dockerfilePath"
}

$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
foreach ($property in @('grade_success_percent', 'step_success_percent', 'green_bean_strength_success_percent')) {
    $value = $config.$property
    if ($null -eq $value -or $value -lt 0 -or $value -gt 100) {
        throw "Valore non valido per ${property}: $value"
    }
}

function New-RefineRow {
    param(
        [string]$Name,
        [int]$NeedCount,
        [int]$Fee,
        [string[]]$Columns,
        [string]$SuccessColumn,
        [int]$SuccessPercent
    )

    $values = foreach ($column in $Columns) {
        if ($column -eq $SuccessColumn) { $SuccessPercent } else { 0 }
    }
    return ((@($Name, $NeedCount, $Fee) + $values) -join '\t')
}

$gradeColumns = @('GRADE_NORMAL', 'GRADE_BRILLIANT', 'GRADE_RARE', 'GRADE_ANCIENT', 'GRADE_LEGENDARY', 'GRADE_MYTH')
$stepColumns = @('STEP_LOWEST', 'STEP_LOW', 'STEP_MID', 'STEP_HIGH', 'STEP_HIGHEST')

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add('Group RefineGradeTables')
$lines.Add('{')
$lines.Add('\tGroup Default')
$lines.Add('\t{')
$lines.Add('\t\t#--#\tNEED_COUNT\tFEE\tGRADE_NORMAL\tGRADE_BRILLIANT\tGRADE_RARE\tGRADE_ANCIENT\tGRADE_LEGENDARY\tGRADE_MYTH')
$lines.Add(('\t\t' + (New-RefineRow -Name 'GRADE_NORMAL' -NeedCount 2 -Fee 30000 -Columns $gradeColumns -SuccessColumn 'GRADE_BRILLIANT' -SuccessPercent $config.grade_success_percent)))
$lines.Add(('\t\t' + (New-RefineRow -Name 'GRADE_BRILLIANT' -NeedCount 2 -Fee 50000 -Columns $gradeColumns -SuccessColumn 'GRADE_RARE' -SuccessPercent $config.grade_success_percent)))
$lines.Add(('\t\t' + (New-RefineRow -Name 'GRADE_RARE' -NeedCount 2 -Fee 70000 -Columns $gradeColumns -SuccessColumn 'GRADE_ANCIENT' -SuccessPercent $config.grade_success_percent)))
$lines.Add(('\t\t' + (New-RefineRow -Name 'GRADE_ANCIENT' -NeedCount 2 -Fee 100000 -Columns $gradeColumns -SuccessColumn 'GRADE_LEGENDARY' -SuccessPercent $config.grade_success_percent)))
$lines.Add(('\t\t' + (New-RefineRow -Name 'GRADE_LEGENDARY' -NeedCount 2 -Fee 150000 -Columns $gradeColumns -SuccessColumn 'GRADE_MYTH' -SuccessPercent $config.grade_success_percent)))
$lines.Add('\t}')
$lines.Add('}')
$lines.Add('Group RefineStepTables')
$lines.Add('{')
$lines.Add('\tGroup Default')
$lines.Add('\t{')
$lines.Add('\t\t#--#\tNEED_COUNT\tFEE\tSTEP_LOWEST\tSTEP_LOW\tSTEP_MID\tSTEP_HIGH\tSTEP_HIGHEST')
$lines.Add(('\t\t' + (New-RefineRow -Name 'STEP_LOWEST' -NeedCount 2 -Fee 20000 -Columns $stepColumns -SuccessColumn 'STEP_LOW' -SuccessPercent $config.step_success_percent)))
$lines.Add(('\t\t' + (New-RefineRow -Name 'STEP_LOW' -NeedCount 2 -Fee 30000 -Columns $stepColumns -SuccessColumn 'STEP_MID' -SuccessPercent $config.step_success_percent)))
$lines.Add(('\t\t' + (New-RefineRow -Name 'STEP_MID' -NeedCount 2 -Fee 40000 -Columns $stepColumns -SuccessColumn 'STEP_HIGH' -SuccessPercent $config.step_success_percent)))
$lines.Add(('\t\t' + (New-RefineRow -Name 'STEP_HIGH' -NeedCount 2 -Fee 50000 -Columns $stepColumns -SuccessColumn 'STEP_HIGHEST' -SuccessPercent $config.step_success_percent)))
$lines.Add('\t}')
$lines.Add('}')
$expectedBlock = $lines -join '\n'
$greenBeanStrengthValues = ((1..6 | ForEach-Object { $config.green_bean_strength_success_percent }) -join '\t')

$dockerfile = [System.IO.File]::ReadAllText($dockerfilePath)
$pattern = '(?s)Group RefineGradeTables\\n\{.*?\}\\nGroup RefineStepTables\\n\{.*?\}(?=\\nGroup RefineStrengthTables)'
$matches = [regex]::Matches($dockerfile, $pattern)
if ($matches.Count -ne 1) {
    throw "Atteso un solo blocco RefineGradeTables/RefineStepTables, trovati $($matches.Count)."
}

if ($Mode -eq 'Apply' -and $matches[0].Value -ne $expectedBlock) {
    $dockerfile = [regex]::Replace($dockerfile, $pattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($match) $expectedBlock }, 1)
    [System.IO.File]::WriteAllText($dockerfilePath, $dockerfile, [System.Text.UTF8Encoding]::new($false))
    $dockerfile = [System.IO.File]::ReadAllText($dockerfilePath)
    $matches = [regex]::Matches($dockerfile, $pattern)
}

if ($matches.Count -ne 1 -or $matches[0].Value -ne $expectedBlock) {
    throw "Il Dockerfile non contiene le percentuali personalizzate. Esegui: powershell -ExecutionPolicy Bypass -File scripts\\sync-dragon-soul-refine.ps1 -Mode Apply"
}

$strengthPattern = '(?s)(?<prefix>Group RefineStrengthTables\\n\{.*?MATERIAL_DS_REFINE_NORMAL\\t)(?<fee>\d+)(?:\\t\d+){6}'
$strengthMatches = [regex]::Matches($dockerfile, $strengthPattern)
if ($strengthMatches.Count -ne 1) {
    throw "Attesa una sola riga MATERIAL_DS_REFINE_NORMAL in RefineStrengthTables, trovate $($strengthMatches.Count)."
}

$greenBeanExpectedPattern = 'MATERIAL_DS_REFINE_NORMAL\\t\d+(?:\\t' + [regex]::Escape([string]$config.green_bean_strength_success_percent) + '){6}$'
if ($Mode -eq 'Apply' -and -not [regex]::IsMatch($strengthMatches[0].Value, $greenBeanExpectedPattern)) {
    $dockerfile = [regex]::Replace($dockerfile, $strengthPattern, [System.Text.RegularExpressions.MatchEvaluator]{
        param($match)
        $match.Groups['prefix'].Value + $match.Groups['fee'].Value + '\t' + $greenBeanStrengthValues
    }, 1)
    [System.IO.File]::WriteAllText($dockerfilePath, $dockerfile, [System.Text.UTF8Encoding]::new($false))
    $dockerfile = [System.IO.File]::ReadAllText($dockerfilePath)
    $strengthMatches = [regex]::Matches($dockerfile, $strengthPattern)
}

if ($strengthMatches.Count -ne 1 -or -not [regex]::IsMatch($strengthMatches[0].Value, $greenBeanExpectedPattern)) {
    throw "Il Dockerfile non contiene la percentuale personalizzata del Chicco del Drago Verde. Esegui: powershell -ExecutionPolicy Bypass -File scripts\\sync-dragon-soul-refine.ps1 -Mode Apply"
}

Write-Output "Dragon Soul refining verificato: grade=$($config.grade_success_percent)% step=$($config.step_success_percent)% chicco-verde=$($config.green_bean_strength_success_percent)%"
