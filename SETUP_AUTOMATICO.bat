@echo off
REM ============================================================================
REM SETUP FOTOS - AUTOMÁTICO
REM Clique neste arquivo e deixe rodar
REM ============================================================================

chcp 65001 > nul
cls
color 0A

echo.
echo ╔════════════════════════════════════════════════════════════════════╗
echo ║         SETUP AUTOMÁTICO - FOTOS DAS 8 MÁQUINAS                    ║
echo ║                    Por favor, aguarde...                           ║
echo ╚════════════════════════════════════════════════════════════════════╝
echo.

REM ============================================================================
REM VERIFICAR PRÉ-REQUISITOS
REM ============================================================================

echo [1/3] Verificando...
if not exist "usinagem.db" (
    color 0C
    echo.
    echo ❌ ERRO: usinagem.db não encontrado!
    echo.
    echo Este arquivo precisa estar na pasta: TCC.VITOR\
    echo.
    echo Verifique se você tá na pasta certa:
    echo C:\Users\vitor\OneDrive\Documentos\Desktop\TCC.VITOR\
    echo.
    pause
    exit /b 1
)

if not exist "setup_fotos_maquinas.py" (
    color 0C
    echo.
    echo ❌ ERRO: setup_fotos_maquinas.py não encontrado!
    echo.
    echo Baixe o arquivo da sessão anterior e coloque em: TCC.VITOR\
    echo.
    pause
    exit /b 1
)

echo ✅ Arquivos encontrados
echo.

REM ============================================================================
REM CRIAR PASTA fotos_maquinas (se não existir)
REM ============================================================================

echo [2/3] Preparando pasta de fotos...

if not exist "fotos_maquinas" (
    mkdir fotos_maquinas
    echo ✅ Pasta criada: fotos_maquinas\
) else (
    echo ✅ Pasta já existe: fotos_maquinas\
)

echo.

REM ============================================================================
REM RODAR SCRIPT PYTHON
REM ============================================================================

echo [3/3] Executando setup (pode levar alguns segundos)...
echo.

python setup_fotos_maquinas.py

if errorlevel 1 (
    color 0C
    echo.
    echo ❌ ERRO ao executar script!
    echo.
    echo Possíveis causas:
    echo 1. Python não está instalado
    echo 2. Faltam imagens na pasta fotos_maquinas\
    echo 3. Arquivo usinagem.db está corrompido
    echo.
    echo Tente de novo ou abra issue no GitHub
    echo.
    pause
    exit /b 1
)

REM ============================================================================
REM SUCESSO
REM ============================================================================

color 0A
echo.
echo ╔════════════════════════════════════════════════════════════════════╗
echo ║                    ✅ SETUP COMPLETO!                             ║
echo ╚════════════════════════════════════════════════════════════════════╝
echo.
echo PRÓXIMOS PASSOS:
echo.
echo 1. Testar LOCALMENTE:
echo    Terminal 1: python app.py
echo    Terminal 2: cd frontend ^&^& npm run dev
echo    Abrir: http://localhost:5173
echo    Aba: 🔧 Manutenção (você deve VER as 8 fotos)
echo.
echo 2. Fazer commit e push:
echo    git add .
echo    git commit -m "feat: adicionar fotos das 8 máquinas"
echo    git push
echo.
echo 3. Verificar em produção (~2 min depois):
echo    https://frontend-xi-two-5l7d05gqtg.vercel.app
echo    Aba: 🔧 Manutenção
echo.
echo ✨ Sistema pronto com fotos!
echo.
pause
