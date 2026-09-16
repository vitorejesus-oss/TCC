# Máquinas do Sistema - v2

## Setor 1: Oficina Central de Manutenção (6 máquinas)

| Nome | Modelo | Fabricante | Função |
|------|--------|-----------|--------|
| Torno Horizontal | Romi Centur 50 | Romi | Torneamento de peças cilíndricas |
| Torno Vertical | Clever VTL | Clever | Torneamento de peças grandes |
| Fresadora Universal | Romi U30 | Romi | Fresamento e abertura de rasgos |
| Mandrilhadora | Tos Varnsdorf | Tos | Alargamento de furos internos |
| Furadeira Radial | Romi GR-40 | Romi | Perfuração radial |
| Serra de Fita | Franho FM-500 | Franho | Corte bruto de material |

## Setor 2: Oficina de Cilindros de Laminação (2 máquinas)

| Nome | Modelo | Fabricante | Função |
|------|--------|-----------|--------|
| Torno CNC Cilindros | Herkules | Herkules | Usinagem de cilindros de laminação |
| Retificadora Cilíndrica | Romi RCG | Romi | Acabamento cilíndrico de precisão |

## Status

- ✅ Backend: `GET /api/maquinas` retorna as 8 máquinas (testado via curl)
- ✅ Frontend: grid de "🔧 Manutenção" mostra 8 máquinas com modelo/fabricante (testado no navegador)
- ✅ Testes: 24/24 pytest passando
- ⚠️ Telegram: não existe comando `/maquinas` no bot atual (`bot_telegram.py` só tem `/start`, `/help`, `/notas`, `/urgente`, `/status`) — não foi adicionado, pois estava fora do escopo desta tarefa ("só substituir dados")

## Notas de implementação

- As máquinas antigas (CENTUR, D1250, FRESADORA, POLITRIZ) são removidas automaticamente por `seed_data()` toda vez que o backend inicia — não foi feita uma edição manual do banco, porque isso teria que ser repetido a cada redeploy (o disco do Railway persiste entre deploys).
- As operações de exemplo (`operacoes`) que referenciavam as máquinas antigas por nome foram atualizadas para os nomes novos, senão a criação de notas quebraria (a alocação de máquina busca por `nome` exato).
- Os campos `modelo` e `fabricante` são colunas novas na tabela `maquinas`, adicionadas via `ALTER TABLE` seguro (mesmo padrão já usado para `localizacao`/`foto_url`/`manual_url`).
