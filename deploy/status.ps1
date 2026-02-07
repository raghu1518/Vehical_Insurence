param(
    [string]$ServiceName = "multilingual-bot"
)

Get-Service -Name $ServiceName -ErrorAction SilentlyContinue | Format-List *
