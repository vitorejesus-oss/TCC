# FASE 0 — Faxina e navegação

Sistema de Automação de Usinagem | Grand Prix SENAI — Pentágono Mecânico

Cinco edições no `frontend/src/App.jsx` mais a troca do `index.css`.
**Nenhuma toca no backend.** Se algo quebrar, é frontend e é reversível.

Faça na ordem. Teste depois de cada uma.

---

## EDIÇÃO 1 — Trocar o CSS

Substitua todo o conteúdo de `frontend/src/index.css` pelo arquivo
`index.css` que veio junto.

Confirme que o `main.jsx` importa ele. Deve ter uma linha assim:

```jsx
import './index.css'
```

Se não tiver, adicione.

---

## EDIÇÃO 2 — Apagar o bloco `<style>` do App.jsx

No `App.jsx`, apague o bloco inteiro que começa na **linha 1132**:

```jsx
      <style>{`
```

e termina na **linha 1412**:

```jsx
      `}</style>
```

Apague as duas linhas e tudo entre elas. São 281 linhas.

**Por que:** esse CSS está dentro do JSX e sobrescreve o `index.css`.
Enquanto ele existir, o tema novo não aparece. Além disso, todo CSS
que você escrever daqui pra frente teria que ser colado ali dentro.

**Teste agora:** `npm run dev` e abra o sistema. Ele deve aparecer com
o tema novo. Se ficar sem estilo nenhum, o `main.jsx` não está
importando o `index.css`.

---

## EDIÇÃO 3 — Corrigir a senha padrão

Duas linhas erradas. O backend usa `Vitor367`, o frontend preenche `123456`.

**Linha 439** — troque:

```jsx
const [loginSenha, setLoginSenha] = useState('123456');
```

por:

```jsx
const [loginSenha, setLoginSenha] = useState('Vitor367');
```

**Linha 1102** — troque `senha 123456` por `senha Vitor367` no texto da dica.

**Por que:** foi isso que fez o "Notificar Quebra" falhar com 401. Quem
clicar em Entrar sem trocar o campo não loga, e todas as ações
protegidas falham sem explicação.

---

## EDIÇÃO 4 — Corrigir o bug de recarga a cada 10 segundos

`PainelBackup` e `PainelEstatisticas` estão definidos **dentro** de
`SistemaAutomacao`, e têm `useEffect` com array vazio:

```jsx
function PainelBackup() {
  useEffect(() => { carregarBackups(); }, []);
```

Como a função é recriada em cada render, o React remonta o componente a
cada poll de 10s e esse efeito dispara de novo. Resultado: essas duas
abas chamam o servidor a cada 10 segundos enquanto estiverem abertas.

**Passo 4.1** — apague as duas linhas de `useEffect`:

- em `PainelBackup` (linha ~1004): `useEffect(() => { carregarBackups(); }, []);`
- em `PainelEstatisticas` (linha ~1040): `useEffect(() => { carregarEstatisticas(); }, []);`

**Passo 4.2** — no componente pai `SistemaAutomacao`, logo depois do
`useEffect` que faz o polling de 10s, adicione:

```jsx
  // Carrega os dados de Backup e Estatísticas quando a tela é aberta,
  // uma vez por abertura. Antes esses fetch ficavam dentro dos painéis,
  // que são recriados a cada render — o efeito disparava a cada poll.
  useEffect(() => {
    if (tab === 'backup') carregarBackups();
    if (tab === 'estatisticas') carregarEstatisticas();
  }, [tab]);
```

**Teste:** abra a aba Estatísticas, abra o DevTools (F12) na aba Network
e espere 30 segundos. Deve haver **uma** chamada a `/api/estatisticas`,
não três.

---

## EDIÇÃO 5 — Navegação por módulos

**Passo 5.1** — Logo depois dos imports, no topo do arquivo (antes de
`function ModalVerMais`), adicione:

```jsx
// Os 10 botões soltos viraram 5 módulos. As telas e os ids de `tab` são
// os mesmos de antes — só a navegação mudou, nenhum painel foi tocado.
// PLANEJAMENTO entra aqui na Fase 3, junto com a Timeline.
const MODULOS = [
  {
    id: 'demandas',
    nome: 'Demandas',
    telas: [
      { id: 'notas', nome: 'Abrir nota' },
      { id: 'sap', nome: 'Importação SAP' },
    ],
  },
  {
    id: 'producao',
    nome: 'Produção',
    telas: [
      { id: 'operador', nome: 'Fila de trabalho' },
    ],
  },
  {
    id: 'ativos',
    nome: 'Manutenção',
    telas: [
      { id: 'manutencao', nome: 'Máquinas' },
    ],
  },
  {
    id: 'gestao',
    nome: 'Gestão',
    telas: [
      { id: 'gestao', nome: 'Indicadores' },
      { id: 'estatisticas', nome: 'Estatísticas' },
      { id: 'relatorio', nome: 'Relatório' },
      { id: 'auditoria', nome: 'Auditoria' },
      { id: 'backup', nome: 'Backup' },
    ],
  },
  {
    id: 'acesso',
    nome: 'Acesso',
    telas: [
      { id: 'login', nome: 'Login' },
    ],
  },
];
```

**Passo 5.2** — No estado de `SistemaAutomacao`, ao lado do
`const [tab, setTab] = useState('operador');`, adicione:

```jsx
  const [modulo, setModulo] = useState('producao');
```

**Passo 5.3** — Ainda dentro de `SistemaAutomacao`, junto das outras
funções, adicione:

```jsx
  // Trocar de módulo leva para a primeira tela dele.
  function abrirModulo(moduloId) {
    const m = MODULOS.find((x) => x.id === moduloId);
    if (!m) return;
    setModulo(moduloId);
    setTab(m.telas[0].id);
  }
```

**Passo 5.4** — Substitua o bloco `<div className="tabs">` inteiro
(linhas 1446 a 1457, os 10 botões) por:

```jsx
      {(() => {
        const moduloAtual = MODULOS.find((m) => m.id === modulo) || MODULOS[0];
        const temSubmenu = moduloAtual.telas.length > 1;

        return (
          <>
            <div className={`modulos ${temSubmenu ? '' : 'sozinho'}`}>
              {MODULOS.map((m) => (
                <button
                  key={m.id}
                  className={`modulo-btn ${modulo === m.id ? 'active' : ''}`}
                  onClick={() => abrirModulo(m.id)}
                >
                  {m.nome}
                </button>
              ))}
            </div>

            {temSubmenu && (
              <div className="telas">
                {moduloAtual.telas.map((t) => (
                  <button
                    key={t.id}
                    className={`tela-btn ${tab === t.id ? 'active' : ''}`}
                    onClick={() => setTab(t.id)}
                  >
                    {t.nome}
                  </button>
                ))}
              </div>
            )}
          </>
        );
      })()}
```

**Não mexa** nas linhas abaixo disso — os `{tab === 'operador' && ...}`
continuam iguais. Os ids de tela são os mesmos, então tudo continua
renderizando como antes.

---

## EDIÇÃO 6 (opcional, mas recomendada) — Tirar os emojis

Os emojis do header e dos títulos dos painéis. Busque e troque:

| De | Para |
|---|---|
| `🏭 Sistema de Automação de Usinagem` | `Sistema de Automação de Usinagem` |
| `⚙️ Fila de Trabalho` | `Fila de Trabalho` |
| `📊 Métricas e Impacto` | `Métricas e Impacto` |
| `📝 Criar Nova Nota` | `Criar Nova Nota` |
| `🔍 Auditoria e Rastreamento` | `Auditoria e Rastreamento` |
| `📥 Importação SAP` | `Importação SAP` |
| `📄 Relatório de Economia (PDF)` | `Relatório de Economia (PDF)` |
| `💾 Backup do Banco de Dados` | `Backup do Banco de Dados` |
| `📈 Estatísticas Customizadas` | `Estatísticas Customizadas` |
| `🔐 Login (JWT) e Área Protegida` | `Login e Área Protegida` |
| `🔧 Manutenção de Máquinas` | `Manutenção de Máquinas` |
| `💬 Chat - Manutenção` | `Chat — Manutenção` |

**Deixe os emojis de status** (`🟢 🔴 ⚪` no card de máquina, `🚨` no
botão de quebra). Ali eles carregam informação, não são decoração.

---

## CHECKLIST DEPOIS DE APLICAR

- [ ] `npm run dev` sobe sem erro
- [ ] Tema novo aparece (azul escuro no header, fonte Barlow)
- [ ] Os 5 módulos aparecem, e Demandas e Gestão mostram submenu
- [ ] Todas as 10 telas antigas continuam abrindo
- [ ] Login com `operador@fabrica.com` / `Vitor367` funciona sem trocar o campo
- [ ] Aba Manutenção: as 8 máquinas aparecem, o modal abre com a foto
- [ ] Chat de manutenção continua enviando e recebendo
- [ ] Network (F12): abrir Estatísticas gera **uma** chamada, não uma a cada 10s
- [ ] `git add . && git commit -m "fase 0: css externo + navegacao por modulos" && git push origin master:main`

---

## O QUE FICOU DE FORA DESTA FASE, DE PROPÓSITO

Os nove painéis (`PainelOperador`, `PainelGestao`, `PainelNotas`, etc.)
continuam aninhados dentro de `SistemaAutomacao`. Isso é o mesmo problema
que você corrigiu nas Features 2, 3 e 4 — eles são recriados a cada
render.

Hoje o sintoma é só desperdício: eles não têm estado próprio, então
remontar não quebra nada visível (o `useEffect` da Edição 4 era a
exceção).

**Mas assim que qualquer um deles ganhar estado** — um filtro, uma
ordenação, um campo de busca — o estado vai zerar a cada 10 segundos.
Quando chegarmos na Fase 2 ou 3, subimos esses painéis para o nível do
módulo passando props. Não vale fazer agora junto com a mudança de
navegação: são duas refatorações ao mesmo tempo, e se quebrar você não
sabe qual foi.
