# GitHub にリポジトリを作成して push するスクリプト
$ErrorActionPreference = "Stop"
$env:Path = [System.Environment]::GetEnvironmentVariable('Path','User') + ';' + [System.Environment]::GetEnvironmentVariable('Path','Machine')

Set-Location $PSScriptRoot

if (-not (gh auth status 2>$null)) {
  Write-Host "GitHub にログインしてください..."
  gh auth login --hostname github.com --git-protocol https --web
}

Write-Host "リポジトリを作成して push します..."
gh repo create shukatsu-kanri --public --source=. --remote=origin --push --description "就活管理ツール（HTML + Claude API）"

Write-Host "完了: https://github.com/$(gh api user -q .login)/shukatsu-kanri"
