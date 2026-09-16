import shutil
from pathlib import Path

print("\n" + "="*60)
print("SETUP FOTOS - VERSAO SIMPLIFICADA")
print("="*60 + "\n")

try:
    # Criar pasta static/fotos_maquinas
    fotos_src = Path("fotos_maquinas")
    fotos_dest = Path("static") / "fotos_maquinas"
    
    if not fotos_src.exists():
        print("❌ Pasta fotos_maquinas nao encontrada!")
        exit(1)
    
    fotos_dest.mkdir(parents=True, exist_ok=True)
    print("✅ Pasta criada/verificada")
    
    # Copiar 8 imagens
    arquivos = [
        "maquina_01_torno_horizontal.jpg",
        "maquina_02_torno_vertical.webp",
        "maquina_03_fresadora_universal.webp",
        "maquina_04_mandrilhadora.jpg",
        "maquina_05_furadeira_radial.jpeg",
        "maquina_06_serra_fita.jpg",
        "maquina_07_torno_cnc_cilindros.jpeg",
        "maquina_08_retificadora_cilindrica.jpeg",
    ]
    
    for arquivo in arquivos:
        src = fotos_src / arquivo
        dst = fotos_dest / arquivo
        if src.exists():
            shutil.copy2(src, dst)
            print(f"✅ {arquivo}")
        else:
            print(f"⚠️  {arquivo} nao encontrado")
    
    print("\n" + "="*60)
    print("✅ FOTOS COPIADAS COM SUCESSO!")
    print("="*60 + "\n")
    
except Exception as e:
    print(f"❌ Erro: {e}")
    exit(1)