#!/usr/bin/env python3
"""
SETUP FOTOS MÁQUINAS v1.0
Roda UMA VEZ na máquina do Vitor após fazer git pull das imagens

Passo a passo:
1. Copiar este arquivo pra: C:\Users\vitor\OneDrive\Documentos\Desktop\TCC.VITOR\
2. Rodar: python setup_fotos_maquinas.py
3. Ver ✅ mensagens de sucesso
4. Fazer git add + commit + push
5. PRONTO!
"""

import sqlite3
import shutil
from pathlib import Path
from datetime import datetime

print("\n" + "="*80)
print("SETUP FOTOS MÁQUINAS - AUTOMÁTICO")
print("="*80)

# ============================================================================
# CONFIGURAÇÃO
# ============================================================================

# Onde este script está rodando (TCC.VITOR/)
SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / "usinagem.db"
FOTOS_SRC = SCRIPT_DIR / "fotos_maquinas"  # Pasta com as 8 fotos
FOTOS_DEST = SCRIPT_DIR / "static" / "fotos_maquinas"  # Onde Flask serve

print(f"\n📍 Diretório: {SCRIPT_DIR}")
print(f"📁 Banco de dados: {DB_PATH}")
print(f"📸 Fotos origem: {FOTOS_SRC}")
print(f"📸 Fotos destino: {FOTOS_DEST}")

# ============================================================================
# VERIFICAÇÕES
# ============================================================================

print("\n[1/4] Verificando pré-requisitos...")

if not DB_PATH.exists():
    print(f"❌ ERRO: Banco não encontrado em {DB_PATH}")
    exit(1)
print(f"   ✅ Banco existe: {DB_PATH}")

if not FOTOS_SRC.exists():
    print(f"❌ ERRO: Pasta de fotos não encontrada em {FOTOS_SRC}")
    exit(1)
print(f"   ✅ Pasta fotos existe: {FOTOS_SRC}")

fotos_encontradas = list(FOTOS_SRC.glob("maquina_*.jpg")) + \
                   list(FOTOS_SRC.glob("maquina_*.jpeg")) + \
                   list(FOTOS_SRC.glob("maquina_*.webp"))

if len(fotos_encontradas) != 8:
    print(f"⚠️  AVISO: Esperava 8 fotos, encontrou {len(fotos_encontradas)}")
    print("   Fotos encontradas:")
    for f in sorted(fotos_encontradas):
        print(f"   - {f.name}")
else:
    print(f"   ✅ 8 fotos encontradas")

# ============================================================================
# CRIAR PASTA DE DESTINO
# ============================================================================

print("\n[2/4] Criando pasta de destino...")

FOTOS_DEST.mkdir(parents=True, exist_ok=True)
print(f"   ✅ Pasta criada: {FOTOS_DEST}")

# ============================================================================
# COPIAR FOTOS
# ============================================================================

print("\n[3/4] Copiando fotos...")

# Mapeamento: arquivo_origem → url_no_banco
mapeamento = {
    "maquina_01_torno_horizontal.jpg": "/static/fotos_maquinas/maquina_01_torno_horizontal.jpg",
    "maquina_02_torno_vertical.webp": "/static/fotos_maquinas/maquina_02_torno_vertical.webp",
    "maquina_03_fresadora_universal.webp": "/static/fotos_maquinas/maquina_03_fresadora_universal.webp",
    "maquina_04_mandrilhadora.jpg": "/static/fotos_maquinas/maquina_04_mandrilhadora.jpg",
    "maquina_05_furadeira_radial.jpeg": "/static/fotos_maquinas/maquina_05_furadeira_radial.jpeg",
    "maquina_06_serra_fita.jpg": "/static/fotos_maquinas/maquina_06_serra_fita.jpg",
    "maquina_07_torno_cnc_cilindros.jpeg": "/static/fotos_maquinas/maquina_07_torno_cnc_cilindros.jpeg",
    "maquina_08_retificadora_cilindrica.jpeg": "/static/fotos_maquinas/maquina_08_retificadora_cilindrica.jpeg",
}

for arquivo_origem, url_banco in mapeamento.items():
    src = FOTOS_SRC / arquivo_origem
    dst = FOTOS_DEST / arquivo_origem
    
    if src.exists():
        shutil.copy2(src, dst)
        print(f"   ✅ {arquivo_origem}")
    else:
        print(f"   ⚠️  Não encontrado: {arquivo_origem}")

# ============================================================================
# ATUALIZAR BANCO DE DADOS
# ============================================================================

print("\n[4/4] Atualizando banco de dados...")

try:
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # Verificar se coluna foto_url existe
    cursor.execute("PRAGMA table_info(maquinas)")
    colunas = [col[1] for col in cursor.fetchall()]
    
    if "foto_url" not in colunas:
        print("   ℹ️  Adicionando coluna foto_url...")
        cursor.execute("ALTER TABLE maquinas ADD COLUMN foto_url TEXT")
        conn.commit()
        print("   ✅ Coluna foto_url adicionada")
    else:
        print("   ℹ️  Coluna foto_url já existe")
    
    # Atualizar foto_url para cada máquina
    atualizacoes = [
        (1, "/static/fotos_maquinas/maquina_01_torno_horizontal.jpg"),
        (2, "/static/fotos_maquinas/maquina_02_torno_vertical.webp"),
        (3, "/static/fotos_maquinas/maquina_03_fresadora_universal.webp"),
        (4, "/static/fotos_maquinas/maquina_04_mandrilhadora.jpg"),
        (5, "/static/fotos_maquinas/maquina_05_furadeira_radial.jpeg"),
        (6, "/static/fotos_maquinas/maquina_06_serra_fita.jpg"),
        (7, "/static/fotos_maquinas/maquina_07_torno_cnc_cilindros.jpeg"),
        (8, "/static/fotos_maquinas/maquina_08_retificadora_cilindrica.jpeg"),
    ]
    
    for maq_id, foto_url in atualizacoes:
        cursor.execute(
            "UPDATE maquinas SET foto_url = ? WHERE id = ?",
            (foto_url, maq_id)
        )
        print(f"   ✅ Máquina {maq_id}: foto_url atualizada")
    
    conn.commit()
    
    # Verificar resultado
    print("\n✅ Verificação final:")
    cursor.execute("SELECT id, nome, foto_url FROM maquinas ORDER BY id")
    for row in cursor.fetchall():
        status = "✅" if row[2] else "❌"
        print(f"   {status} ID {row[0]}: {row[1]:30s} → {row[2] or 'SEM FOTO'}")
    
    conn.close()
    
except Exception as e:
    print(f"❌ ERRO ao atualizar banco: {e}")
    exit(1)

# ============================================================================
# RESUMO FINAL
# ============================================================================

print("\n" + "="*80)
print("✅ SETUP COMPLETO!")
print("="*80)

print("""
PRÓXIMOS PASSOS:

1. Ter certeza que tudo tá funcionando:
   - Rodar app.py localmente: python app.py
   - Abrir http://localhost:5000
   - Clicar na aba "🔧 Manutenção"
   - Você deve VER as fotos das 8 máquinas!

2. Fazer commit no Git:
   git add .
   git commit -m "feat: adicionar fotos das 8 máquinas reais"
   git push

3. Railway vai atualizar sozinho em ~2 min
   - Verificar: https://automacao-usinagem-backend-production.up.railway.app
   - Abrir aba "🔧 Manutenção"
   - As fotos devem aparecer em produção!

DÚVIDAS? Abra este arquivo em editor de texto (setup_fotos_maquinas.py)
""")

print("\n" + "="*80 + "\n")
