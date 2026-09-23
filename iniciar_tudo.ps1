# Sobe os tres processos da demonstracao: backend, frontend e bot do Telegram.
# Cada um abre em sua propria janela (fechar a janela derruba o processo).
#   Uso: duplo clique em iniciar_tudo.bat  ou  .\iniciar_tudo.ps1
#   -SemBot  sobe so backend e frontend
param([switch]$SemBot)

$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $raiz

function Ler-Env($chave) {
    $arquivo = Join-Path $raiz '.env'
    if (-not (Test-Path $arquivo)) { return '' }
    $linha = Get-Content $arquivo -Encoding UTF8 | Where-Object { $_ -match "^\s*$chave\s*=" } | Select-Object -Last 1
    if (-not $linha) { return '' }
    return (($linha -split '=', 2)[1]).Trim().Trim('"').Trim("'")
}

Write-Host '== Sistema de Automacao de Usinagem: subindo os processos ==' -ForegroundColor Cyan

# --- Verificacoes do .env (nunca imprime valores) ---
$subirBot = -not $SemBot
if (-not (Test-Path (Join-Path $raiz '.env'))) {
    Write-Host '[AVISO] Arquivo .env nao encontrado. Copie .env.example para .env e preencha.' -ForegroundColor Yellow
    $subirBot = $false
} else {
    if (-not (Ler-Env 'BOT_SERVICE_TOKEN')) {
        Write-Host '[AVISO] BOT_SERVICE_TOKEN ausente ou vazio no .env: o bot NAO sera iniciado.' -ForegroundColor Yellow
        Write-Host '        Gere um com: python -c "import secrets; print(secrets.token_urlsafe(32))"' -ForegroundColor Yellow
        Write-Host '        e coloque em BOT_SERVICE_TOKEN=... no .env (o backend le o mesmo valor).' -ForegroundColor Yellow
        $subirBot = $false
    }
    if (-not (Ler-Env 'TELEGRAM_TOKEN')) {
        Write-Host '[AVISO] TELEGRAM_TOKEN ausente no .env: o bot NAO sera iniciado.' -ForegroundColor Yellow
        $subirBot = $false
    }
}

if (-not (Test-Path (Join-Path $raiz 'frontend\node_modules'))) {
    Write-Host '[AVISO] frontend\node_modules nao existe. Rode "npm install" dentro de frontend\ primeiro.' -ForegroundColor Yellow
}

# --- Processos ---
Start-Process powershell -ArgumentList '-NoExit', '-Command', "`$Host.UI.RawUI.WindowTitle='Backend :5000'; Set-Location '$raiz'; python app.py"
Write-Host '[OK] Backend       -> http://127.0.0.1:5000' -ForegroundColor Green

Start-Process powershell -ArgumentList '-NoExit', '-Command', "`$Host.UI.RawUI.WindowTitle='Frontend :5173'; Set-Location '$raiz\frontend'; npm run dev"
Write-Host '[OK] Frontend      -> http://localhost:5173' -ForegroundColor Green

if ($subirBot) {
    # Da ao backend um instante para abrir a porta antes do bot fazer o primeiro pedido.
    Start-Sleep -Seconds 3
    Start-Process powershell -ArgumentList '-NoExit', '-Command', "`$Host.UI.RawUI.WindowTitle='Bot Telegram'; Set-Location '$raiz'; python bot_telegram.py"
    $alvo = Ler-Env 'BOT_BACKEND_URL'
    if (-not $alvo) { $alvo = 'http://127.0.0.1:5000 (padrao)' }
    Write-Host "[OK] Bot Telegram  -> backend alvo: $alvo" -ForegroundColor Green
} else {
    Write-Host '[--] Bot Telegram  -> NAO iniciado (veja os avisos acima)' -ForegroundColor Yellow
}

Write-Host ''
Write-Host 'Para encerrar, feche as janelas abertas.' -ForegroundColor Gray
