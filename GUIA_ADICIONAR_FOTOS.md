# 📋 GUIA: ADICIONAR FOTOS DAS 8 MÁQUINAS AO SISTEMA

**Tempo total: 5-10 minutos**

---

## 🎯 OBJETIVO

Fazer as fotos das 8 máquinas aparecerem no painel de manutenção (aba 🔧).

---

## ⚙️ PASSO A PASSO

### **PASSO 1: Preparar a pasta de fotos**

Na máquina do Vitor (`C:\Users\vitor\OneDrive\Documentos\Desktop\TCC.VITOR\`):

```
1. Criar pasta: fotos_maquinas
   - Clicar direito → Nova Pasta → digitar "fotos_maquinas"

2. Colocar as 8 imagens nessa pasta (com ESTES nomes EXATOS):
   ✅ maquina_01_torno_horizontal.jpg
   ✅ maquina_02_torno_vertical.webp
   ✅ maquina_03_fresadora_universal.webp
   ✅ maquina_04_mandrilhadora.jpg
   ✅ maquina_05_furadeira_radial.jpeg
   ✅ maquina_06_serra_fita.jpg
   ✅ maquina_07_torno_cnc_cilindros.jpeg
   ✅ maquina_08_retificadora_cilindrica.jpeg

Resultado esperado:
C:\Users\vitor\OneDrive\Documentos\Desktop\TCC.VITOR\fotos_maquinas\
├── maquina_01_torno_horizontal.jpg
├── maquina_02_torno_vertical.webp
├── maquina_03_fresadora_universal.webp
├── maquina_04_mandrilhadora.jpg
├── maquina_05_furadeira_radial.jpeg
├── maquina_06_serra_fita.jpg
├── maquina_07_torno_cnc_cilindros.jpeg
└── maquina_08_retificadora_cilindrica.jpeg
```

---

### **PASSO 2: Rodar o script de setup**

No terminal do Vitor (`C:\Users\vitor\OneDrive\Documentos\Desktop\TCC.VITOR\`):

```bash
# Terminal: PowerShell ou CMD

# Navegar pra pasta do projeto
cd C:\Users\vitor\OneDrive\Documentos\Desktop\TCC.VITOR

# Rodar o script (UMA VEZ APENAS)
python setup_fotos_maquinas.py
```

**Você deve ver:**
```
================================================================================
SETUP FOTOS MÁQUINAS - AUTOMÁTICO
================================================================================

📍 Diretório: C:\Users\vitor\OneDrive\Documentos\Desktop\TCC.VITOR
📁 Banco de dados: ...\usinagem.db
📸 Fotos origem: ...\fotos_maquinas
📸 Fotos destino: ...\static\fotos_maquinas

[1/4] Verificando pré-requisitos...
   ✅ Banco existe: ...
   ✅ Pasta fotos existe: ...
   ✅ 8 fotos encontradas

[2/4] Criando pasta de destino...
   ✅ Pasta criada: ...\static\fotos_maquinas

[3/4] Copiando fotos...
   ✅ maquina_01_torno_horizontal.jpg
   ✅ maquina_02_torno_vertical.webp
   ... (6 mais)

[4/4] Atualizando banco de dados...
   ✅ Máquina 1: foto_url atualizada
   ✅ Máquina 2: foto_url atualizada
   ... (6 mais)

✅ SETUP COMPLETO!
```

**Se vir ✅ em tudo = SUCESSO!**

---

### **PASSO 3: Testar LOCALMENTE**

Antes de fazer push, testar se funcionou no seu computador:

```bash
# Terminal 1: Backend
cd C:\Users\vitor\OneDrive\Documentos\Desktop\TCC.VITOR
python app.py
# Aguardar: "Running on http://127.0.0.1:5000"

# Terminal 2: Frontend
cd C:\Users\vitor\OneDrive\Documentos\Desktop\TCC.VITOR\frontend
npm run dev
# Aguardar: "http://localhost:5173"
```

**Teste no navegador:**

1. Abrir: http://localhost:5173
2. Login com: operador@fabrica.com / Vitor367
3. Clicar na aba: **🔧 Manutenção**
4. Você deve VER as fotos das 8 máquinas!

**Se vê as fotos = ✅ SUCESSO LOCAL!**

---

### **PASSO 4: Fazer Commit + Push**

```bash
# Terminal (na pasta TCC.VITOR):

# Ver arquivos novos
git status

# Adicionar tudo
git add .

# Fazer commit
git commit -m "feat: adicionar fotos das 8 máquinas + script setup"

# Enviar pra GitHub
git push
```

**Se não tem Git configurado ainda:**
```bash
# Configurar Git (só precisa UMA VEZ)
git config --global user.name "Vitor"
git config --global user.email "vitor.e.jesus@aluno.senai.br"

# Depois fazer commit + push normal
```

---

### **PASSO 5: Verificar em PRODUÇÃO**

Railway vai atualizar automaticamente em ~2 minutos.

```
1. Abrir: https://frontend-xi-two-5l7d05gqtg.vercel.app
2. Login com: operador@fabrica.com / Vitor367
3. Clicar: aba 🔧 Manutenção
4. Você deve VER as fotos lá também!
```

**Se vê as fotos = ✅ SUCESSO EM PRODUÇÃO!**

---

## ⚠️ TROUBLESHOOTING

### **Problema: "Script não roda"**
```
Solução: Ter certeza que você tá na pasta certa:
cd C:\Users\vitor\OneDrive\Documentos\Desktop\TCC.VITOR
python setup_fotos_maquinas.py
```

### **Problema: "Arquivo não encontrado" (fotos_maquinas)"**
```
Solução: Ter certeza que:
1. Pasta "fotos_maquinas" existe em TCC.VITOR/
2. Os 8 arquivos têm os nomes EXATOS (maquina_01_..., etc)
3. Nenhum typo nos nomes
```

### **Problema: "Fotos aparecem localmente mas não em produção"**
```
Solução:
1. Fazer: git status
2. Ver se aparecem: fotos_maquinas/ (pasta com fotos)
3. Se não aparecer: fazer git add fotos_maquinas/
4. Depois: git commit + git push
```

### **Problema: "Coluna já existe" (ao rodar script 2x)"**
```
Solução: Tudo bem! O script detecta e pula.
Pode rodar quantas vezes quiser, é idempotente.
```

---

## ✅ CHECKLIST FINAL

Antes de chamar de "pronto":

- [ ] Pasta `fotos_maquinas` criada com 8 imagens
- [ ] Script `setup_fotos_maquinas.py` rodou sem erro
- [ ] Vê as fotos localmente (localhost:5173, aba Manutenção)
- [ ] Fez commit + push
- [ ] Vê as fotos em produção (Vercel, aba Manutenção)
- [ ] Telegram Bot tá recebendo notificações (quando quebra máquina)

Se tudo ✅ = **PRONTO PARA APRESENTAÇÃO!**

---

## 📞 DÚVIDAS?

Reler este arquivo (é um guia simples e claro).

**Não tem dúvida?** Então vamos pra próxima fase: Desenhos Técnicos profissional.
