import React, { useState, useEffect, useRef } from 'react';
import { io } from 'socket.io-client';

const BACKEND_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';
const API_URL = `${BACKEND_URL}/api`;
const SOCKET_URL = import.meta.env.VITE_SOCKET_URL || BACKEND_URL;

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
      { id: 'catalogo', nome: 'Catálogo de peças' },
    ],
  },
  {
    id: 'planejamento',
    nome: 'Planejamento',
    telas: [
      { id: 'programacao', nome: 'Programação' },
      { id: 'busca', nome: 'Buscar OS' },
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
      // `papeis` = quem vê a tela (o backend também exige: /api/estatisticas)
      { id: 'estatisticas', nome: 'Estatísticas', papeis: ['coordenador', 'gestor', 'diretor'] },
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

const ROTULOS_FICHA = {
  material: 'Material',
  dimensoes: 'Dimensões',
  tolerancia: 'Tolerância',
  aplicacao: 'Aplicação',
  observacoes_tecnicas: 'Observações técnicas',
};

function formatarMin(min) {
  if (min === null || min === undefined) return '—';
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h ? `${h}h${String(m).padStart(2, '0')}` : `${m}min`;
}

// "há 2d 3h" / "há 45min" para o atraso de uma OS.
function formatarAtraso(min) {
  if (min === null || min === undefined) return '—';
  const d = Math.floor(min / 1440);
  const h = Math.floor((min % 1440) / 60);
  if (d) return `há ${d}d ${h}h`;
  if (h) return `há ${h}h${String(min % 60).padStart(2, '0')}`;
  return `há ${min}min`;
}

function formatarDataHora(ts) {
  if (!ts) return '—';
  const d = new Date(ts);
  return Number.isNaN(d.getTime())
    ? ts
    : d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

const ROTULOS_STATUS_OS = { PLANEJAMENTO: 'Planejamento', USINANDO: 'Em usinagem', CONCLUIDA: 'Concluída' };
const FILTROS_VAZIOS = {
  q: '', maquina_id: '', status: '', prioridade: '', criada_de: '', criada_ate: '',
  concluida_de: '', concluida_ate: '', operador: '', em_atraso: false,
};

// Catálogo de peças: o que já tem desenho e ficha técnica e o que falta, para a
// equipe saber o que cadastrar. Module-level (estado próprio, sobrevive ao poll).
function CatalogoPecas() {
  const [pecas, setPecas] = useState(null);
  const [soPendentes, setSoPendentes] = useState(false);
  const [erro, setErro] = useState('');

  useEffect(() => {
    fetch(`${API_URL}/pecas`)
      .then((r) => r.json())
      .then(setPecas)
      .catch(() => setErro('Não consegui carregar o catálogo'));
  }, []);

  if (erro) return <div className="painel"><p>{erro}</p></div>;
  if (!pecas) return <div className="painel">Carregando...</div>;

  // Desenho real = PDF que existe E não é placeholder (desenhos_tecnicos/PLACEHOLDERS.txt).
  const desenhoReal = (p) => p.tem_desenho && !p.desenho_provisorio;
  const pendente = (p) => !desenhoReal(p) || p.ficha_faltando.length > 0;
  const visiveis = soPendentes ? pecas.filter(pendente) : pecas;
  const comDesenho = pecas.filter(desenhoReal).length;
  const comPlaceholder = pecas.filter((p) => p.desenho_provisorio).length;
  const fichaCompleta = pecas.filter((p) => p.ficha_faltando.length === 0).length;

  return (
    <div className="painel">
      <h2>Catálogo de peças</h2>
      <p className="texto-suave" style={{ marginBottom: 14 }}>
        {comDesenho} de {pecas.length} peça(s) com desenho real{comPlaceholder > 0 && ` (${comPlaceholder} só com placeholder)`} · {fichaCompleta} com ficha técnica completa.
        Desenho e ficha são cadastrados por quem tem o desenho em mãos (ficha: coluna do CSV de importação); o sistema não gera medidas.
      </p>
      <label style={{ display: 'block', marginBottom: 12 }}>
        <input type="checkbox" checked={soPendentes} onChange={(e) => setSoPendentes(e.target.checked)} />{' '}
        Mostrar só peças com pendência
      </label>
      <div className="tabela-wrapper">
        <table>
          <thead>
            <tr><th>Código</th><th>Peça</th><th>Desenho</th><th>Ficha cadastrada</th><th>Falta cadastrar</th></tr>
          </thead>
          <tbody>
            {visiveis.map((p) => (
              <tr key={p.codigo}>
                <td className="mono">{p.codigo}</td>
                <td>{p.nome}</td>
                <td>
                  {p.desenho_provisorio ? (
                    <a href={`${API_URL}/pecas/${encodeURIComponent(p.codigo)}/desenho`} target="_blank" rel="noopener noreferrer">⚠️ Placeholder</a>
                  ) : p.tem_desenho ? (
                    <a href={`${API_URL}/pecas/${encodeURIComponent(p.codigo)}/desenho`} target="_blank" rel="noopener noreferrer">✅ Abrir PDF</a>
                  ) : (
                    <span className="texto-suave">— sem desenho</span>
                  )}
                </td>
                <td>
                  {Object.keys(p.ficha).length === 0 ? (
                    <span className="texto-suave">—</span>
                  ) : (
                    Object.keys(ROTULOS_FICHA).filter((campo) => p.ficha[campo]).map((campo) => (
                      <div key={campo}><strong>{ROTULOS_FICHA[campo]}:</strong> {p.ficha[campo]}</div>
                    ))
                  )}
                </td>
                <td>
                  {p.ficha_faltando.length === 0 && desenhoReal(p) ? (
                    <span style={{ color: 'var(--verde)' }}>Completa</span>
                  ) : (
                    <span>
                      {!desenhoReal(p) && (p.desenho_provisorio ? 'Desenho real' : 'Desenho')}
                      {!desenhoReal(p) && p.ficha_faltando.length > 0 && ' · '}
                      {p.ficha_faltando.map((c) => ROTULOS_FICHA[c]).join(', ')}
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {visiveis.length === 0 && (
              <tr><td colSpan="5" className="texto-suave">Nenhuma peça com pendência.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Busca de OS para a supervisão: filtros combináveis, tabela ordenável e
// paginada (tudo no servidor, em GET /api/ordens-servico). Cada linha abre o
// "Ver Mais" da nota da OS.
function BuscaOS({ token }) {
  const [filtros, setFiltros] = useState(FILTROS_VAZIOS);
  const [ordenar, setOrdenar] = useState('criada_em');
  const [direcao, setDirecao] = useState('desc');
  const [porPagina, setPorPagina] = useState(20);
  const [resultado, setResultado] = useState(null);
  const [erro, setErro] = useState('');
  const [carregando, setCarregando] = useState(false);
  const [maquinas, setMaquinas] = useState([]);
  const [notaAberta, setNotaAberta] = useState(null);

  async function buscar({ pagina = 1, ord = ordenar, dir = direcao, pp = porPagina, f = filtros } = {}) {
    const params = new URLSearchParams({ pagina, por_pagina: pp, ordenar: ord, direcao: dir });
    Object.entries(f).forEach(([k, v]) => {
      if (v === '' || v === false) return;
      params.set(k, v === true ? '1' : v);
    });
    setCarregando(true);
    setErro('');
    try {
      const res = await fetch(`${API_URL}/ordens-servico?${params}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.erro || 'Erro na busca');
      setResultado(data);
    } catch (e) {
      setErro(e.message);
    } finally {
      setCarregando(false);
    }
  }

  useEffect(() => {
    fetch(`${API_URL}/maquinas`).then((r) => r.json()).then(setMaquinas).catch(() => {});
    buscar();
  }, []);

  const mudar = (campo) => (e) =>
    setFiltros({ ...filtros, [campo]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  function ordenarPor(coluna) {
    const dir = ordenar === coluna && direcao === 'asc' ? 'desc' : 'asc';
    setOrdenar(coluna);
    setDirecao(dir);
    buscar({ ord: coluna, dir });
  }

  function limpar() {
    setFiltros(FILTROS_VAZIOS);
    buscar({ f: FILTROS_VAZIOS });
  }

  const cabecalho = (coluna, rotulo) => (
    <th className="th-ordenavel" onClick={() => ordenarPor(coluna)} title="Ordenar">
      {rotulo}{ordenar === coluna ? (direcao === 'asc' ? ' ▲' : ' ▼') : ''}
    </th>
  );

  return (
    <div className="painel">
      <h2>Buscar ordens de serviço</h2>

      <form className="filtros-os" onSubmit={(e) => { e.preventDefault(); buscar(); }}>
        <label className="filtro-largo">Busca livre
          <input value={filtros.q} onChange={mudar('q')} placeholder="nº da OS ou da nota, código ou nome da peça, solicitante" />
        </label>
        <label>Máquina
          <select value={filtros.maquina_id} onChange={mudar('maquina_id')}>
            <option value="">Todas</option>
            {maquinas.map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}
          </select>
        </label>
        <label>Situação
          <select value={filtros.status} onChange={mudar('status')}>
            <option value="">Todas</option>
            {Object.entries(ROTULOS_STATUS_OS).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
          </select>
        </label>
        <label>Prioridade
          <select value={filtros.prioridade} onChange={mudar('prioridade')}>
            <option value="">Todas</option>
            <option value="NORMAL">Normal</option>
            <option value="URGENTE">Urgente</option>
          </select>
        </label>
        <label>Operador
          <input value={filtros.operador} onChange={mudar('operador')} placeholder="e-mail ou parte" />
        </label>
        <label>Criada de <input type="date" value={filtros.criada_de} onChange={mudar('criada_de')} /></label>
        <label>Criada até <input type="date" value={filtros.criada_ate} onChange={mudar('criada_ate')} /></label>
        <label>Concluída de <input type="date" value={filtros.concluida_de} onChange={mudar('concluida_de')} /></label>
        <label>Concluída até <input type="date" value={filtros.concluida_ate} onChange={mudar('concluida_ate')} /></label>
        <label className="filtro-check">
          <input type="checkbox" checked={filtros.em_atraso} onChange={mudar('em_atraso')} /> Só em atraso
        </label>
        <div className="filtro-acoes">
          <button type="submit" className="btn-nota" style={{ width: 'auto', padding: '10px 22px' }}>Buscar</button>
          <button type="button" className="btn-pequeno" onClick={limpar}>Limpar filtros</button>
        </div>
      </form>

      {erro && <p style={{ color: 'var(--vermelho)', margin: '12px 0' }}>{erro}</p>}

      {resultado && (
        <>
          <p className="texto-suave" style={{ margin: '14px 0 8px' }}>
            {carregando ? 'Buscando...' : `${resultado.total} OS encontrada(s)`}
          </p>
          <div className="tabela-wrapper">
            <table>
              <thead>
                <tr>
                  {cabecalho('numero', 'OS')}
                  {cabecalho('peca', 'Peça')}
                  {cabecalho('status', 'Situação')}
                  {cabecalho('prioridade', 'Prioridade')}
                  {cabecalho('maquina_atual', 'Máquina atual')}
                  {cabecalho('planejado_min', 'Planejado × Realizado')}
                  {cabecalho('atraso_min', 'Atraso')}
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {resultado.itens.map((o) => (
                  <tr key={o.id} className="linha-clicavel" onClick={() => setNotaAberta(o.nota_id)}>
                    <td><strong>{o.numero}</strong><div className="texto-suave mono">{o.nota_numero}</div></td>
                    <td>{o.peca_nome}<div className="texto-suave mono">{o.peca_codigo}</div></td>
                    <td><span className="status-badge">{ROTULOS_STATUS_OS[o.status] || o.status}</span></td>
                    <td><span className={o.prioridade === 'URGENTE' ? 'badge-urgente' : 'badge-normal'}>{o.prioridade}</span></td>
                    <td>{o.maquina_atual || <span className="texto-suave">—</span>}</td>
                    <td className="mono">{formatarMin(o.planejado_min)} × {formatarMin(o.realizado_min)}</td>
                    <td>{o.em_atraso
                      ? <span style={{ color: 'var(--vermelho)', fontWeight: 600 }}>{formatarAtraso(o.atraso_min)}</span>
                      : <span className="texto-suave">—</span>}</td>
                    <td><button className="btn-pequeno" onClick={(e) => { e.stopPropagation(); setNotaAberta(o.nota_id); }}>Ver Mais</button></td>
                  </tr>
                ))}
                {resultado.itens.length === 0 && (
                  <tr><td colSpan="8" className="texto-suave">Nenhuma OS com esses filtros.</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="paginacao">
            <button className="btn-pequeno" disabled={resultado.pagina <= 1 || carregando}
                    onClick={() => buscar({ pagina: resultado.pagina - 1 })}>← Anterior</button>
            <span>Página {resultado.pagina} de {resultado.paginas}</span>
            <button className="btn-pequeno" disabled={resultado.pagina >= resultado.paginas || carregando}
                    onClick={() => buscar({ pagina: resultado.pagina + 1 })}>Próxima →</button>
            <select value={porPagina} onChange={(e) => { const pp = Number(e.target.value); setPorPagina(pp); buscar({ pp }); }}>
              {[10, 20, 50].map((n) => <option key={n} value={n}>{n} por página</option>)}
            </select>
          </div>
        </>
      )}

      {notaAberta && <ModalVerMais notaId={notaAberta} token={token} onClose={() => setNotaAberta(null)} />}
    </div>
  );
}

// Vínculo do Telegram (tela Acesso). Fora do componente principal pelo mesmo
// motivo do ModalVerMais: a contagem regressiva perderia o estado a cada poll.
function VinculoTelegram({ token }) {
  const [vinculado, setVinculado] = useState(null); // null = carregando
  const [codigo, setCodigo] = useState(null);
  const [fim, setFim] = useState(0); // instante (ms) em que o código expira
  const [restante, setRestante] = useState(0);
  const [erro, setErro] = useState('');
  const headers = { Authorization: `Bearer ${token}` };

  async function consultarStatus() {
    try {
      const res = await fetch(`${API_URL}/telegram/status`, { headers });
      if (res.ok) setVinculado((await res.json()).vinculado);
    } catch (e) {
      console.error(e);
    }
  }

  async function gerar() {
    setErro('');
    try {
      const res = await fetch(`${API_URL}/telegram/gerar-codigo`, { method: 'POST', headers });
      const data = await res.json();
      if (!res.ok) { setErro(data.erro || 'Não foi possível gerar o código'); return; }
      setCodigo(data.codigo);
      setFim(Date.now() + data.validade_minutos * 60 * 1000);
    } catch (e) {
      setErro('Não consegui falar com o servidor');
    }
  }

  useEffect(() => { consultarStatus(); }, [token]);

  // Contagem regressiva; enquanto o código vale, confere a cada 3s se o
  // vínculo já foi feito no Telegram para trocar a tela sozinha.
  useEffect(() => {
    if (!codigo) return undefined;
    const tick = setInterval(() => {
      const seg = Math.max(0, Math.round((fim - Date.now()) / 1000));
      setRestante(seg);
      if (seg === 0) { setCodigo(null); }
    }, 1000);
    const conferir = setInterval(consultarStatus, 3000);
    setRestante(Math.max(0, Math.round((fim - Date.now()) / 1000)));
    return () => { clearInterval(tick); clearInterval(conferir); };
  }, [codigo, fim]);

  const mm = String(Math.floor(restante / 60)).padStart(2, '0');
  const ss = String(restante % 60).padStart(2, '0');

  return (
    <div style={{ marginTop: 24 }} data-testid="vinculo-telegram">
      <h3 style={{ marginBottom: 10 }}>Telegram</h3>
      {vinculado === null ? (
        <p>Verificando...</p>
      ) : vinculado ? (
        <p>✅ Sua conta já está vinculada a um Telegram.</p>
      ) : codigo ? (
        <div>
          <div style={{ fontSize: 40, fontWeight: 700, letterSpacing: 8, background: 'var(--cinza-bg)', border: '1px solid var(--cinza-borda)', borderRadius: 4, padding: '12px 20px', display: 'inline-block' }}>
            {codigo}
          </div>
          <p style={{ marginTop: 10 }}>Expira em <strong>{mm}:{ss}</strong>. No Telegram, envie: <strong>/vincular {codigo}</strong></p>
        </div>
      ) : (
        <div>
          <button className="btn-nota" style={{ width: 'auto', padding: '12px 24px' }} onClick={gerar}>
            Gerar código de vínculo
          </button>
          <p style={{ marginTop: 8, color: 'var(--cinza-texto)', fontSize: 13 }}>
            Gera um código de 6 dígitos para usar com /vincular no bot.
          </p>
        </div>
      )}
      {erro && <p style={{ color: 'var(--vermelho)', marginTop: 8 }}>{erro}</p>}
    </div>
  );
}

// Feature 2 - Modal "Ver Mais": detalhes completos de uma nota.
// Definida FORA do componente principal (não aninhada) de propósito: se
// ficasse aninhada, cada re-render de SistemaAutomacao (o polling de 10s,
// qualquer evento do WebSocket) criaria uma nova referência de função e o
// React remontaria o modal do zero, voltando pra "Carregando..." toda hora.
function ModalVerMais({ notaId, token, onClose }) {
  const [detalhes, setDetalhes] = useState(null);
  const [carregando, setCarregando] = useState(true);
  const [erroModal, setErroModal] = useState(null);

  useEffect(() => {
    fetch(`${API_URL}/notas/${notaId}/detalhes`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}
    })
      .then(async (r) => {
        const data = await r.json();
        if (!r.ok) {
          throw new Error(data.erro || (r.status === 401 ? 'Faça login para ver os detalhes' : 'Erro ao carregar nota'));
        }
        setDetalhes(data);
      })
      .catch((err) => setErroModal(err.message))
      .finally(() => setCarregando(false));
  }, [notaId, token]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-detalhes" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>

        {carregando && <p>Carregando detalhes...</p>}

        {!carregando && erroModal && (
          <>
            <p>{erroModal}</p>
            <div className="modal-buttons">
              <button onClick={onClose} className="btn-primary">Fechar</button>
            </div>
          </>
        )}

        {!carregando && detalhes && (
          <>
            <h2>📋 Nota {detalhes.numero}</h2>

            <section className="modal-section">
              <h3>📦 Peça</h3>
              <p><strong>Nome:</strong> {detalhes.peca.nome}</p>
              <p><strong>Código:</strong> {detalhes.peca.codigo}</p>
              {detalhes.peca.descricao && (
                <p><strong>Descrição:</strong> {detalhes.peca.descricao}</p>
              )}
              {/* Ficha técnica: campo vazio não aparece (nada de "não informado") */}
              {Object.keys(ROTULOS_FICHA).filter((campo) => detalhes.peca.ficha?.[campo]).map((campo) => (
                <p key={campo}><strong>{ROTULOS_FICHA[campo]}:</strong> {detalhes.peca.ficha[campo]}</p>
              ))}
            </section>

            <section className="modal-section">
              <h3>📐 Desenho técnico</h3>
              {detalhes.peca.tem_desenho ? (
                <>
                  <a className="btn-pequeno" href={`${API_URL}/pecas/${encodeURIComponent(detalhes.peca.codigo)}/desenho`}
                     target="_blank" rel="noopener noreferrer">
                    {detalhes.peca.desenho_provisorio ? '📄 Abrir documento provisório (PDF)' : '📄 Abrir desenho (PDF)'}
                  </a>
                  {detalhes.peca.desenho_provisorio && (
                    <p className="aviso-provisorio">⚠️ Documento provisório: o desenho técnico oficial ainda não foi cadastrado.</p>
                  )}
                </>
              ) : (
                <p className="texto-suave">Desenho não cadastrado</p>
              )}
            </section>

            <section className="modal-section">
              <h3>🔧 Ordem de Serviço</h3>
              {detalhes.ordem_servico ? (
                <>
                  <p><strong>Número:</strong> {detalhes.ordem_servico.numero}</p>
                  <p><strong>Status:</strong> {detalhes.ordem_servico.status}</p>
                  <p><strong>Tempo total:</strong> {detalhes.ordem_servico.tempo_total} min</p>
                </>
              ) : (
                <p>Ainda não processada em uma OS.</p>
              )}
              {detalhes.alocacoes.length > 0 && (
                <ul>
                  {detalhes.alocacoes.map((a, i) => (
                    <li key={i}>
                      {a.sequencia}. {a.maquina_nome} — {a.status}
                      {a.inicio_real && (
                        <div className="texto-suave">
                          ⏱️ Usinagem: <strong>{formatarMin(a.tempo_usinagem_min)}</strong>
                          {a.paradas && a.paradas.length > 0 && (
                            <> · Parado: <strong>{formatarMin(a.tempo_parado_min)}</strong>
                              {' '}({formatarMin(a.tempo_parado_expediente_min)} de expediente)</>
                          )}
                        </div>
                      )}
                      {(a.paradas || []).map((p, j) => (
                        <div key={j} className="texto-suave aviso-parada">
                          🔴 Parada {j + 1}: {formatarDataHora(p.inicio)} → {p.aberta ? 'em andamento' : formatarDataHora(p.fim)}
                          {' '}({formatarMin(p.duracao_min)} · {formatarMin(p.expediente_min)} de expediente)
                        </div>
                      ))}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="modal-section">
              <h3>⏱️ Economia (automação)</h3>
              {detalhes.economia_minutos !== null ? (
                <p>
                  <strong>Economia:</strong>{' '}
                  <span style={{ color: 'var(--verde)', fontWeight: 'bold' }}>
                    +{detalhes.economia_minutos} min ({detalhes.economia_percentual}%)
                  </span>
                </p>
              ) : (
                <p>Nota ainda não processada.</p>
              )}
            </section>

            <section className="modal-section">
              <h3>👤 Solicitante</h3>
              <p>{detalhes.solicitante || '-'}</p>
              <p><small>{new Date(detalhes.criada_em).toLocaleString('pt-BR')}</small></p>
            </section>

            <section className="modal-section">
              <h3>📊 Histórico</h3>
              <div className="historico-list">
                {detalhes.historico.length > 0 ? (
                  detalhes.historico.map((item, idx) => (
                    <div key={idx} className="historico-item">
                      <small>{new Date(item.criado_em).toLocaleString('pt-BR')}</small>
                      <p><strong>{item.tipo_evento}</strong> — {item.descricao}</p>
                    </div>
                  ))
                ) : (
                  <p>Sem histórico</p>
                )}
              </div>
            </section>

            <div className="modal-buttons">
              <button onClick={onClose} className="btn-primary">Fechar</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// Feature 3 - Manutenção: modal de detalhe/ações de uma máquina.
// Também module-level (não aninhado) pelo mesmo motivo do ModalVerMais.
// Feature 4 - Chat de manutenção (operador ↔ coordenador/gestor/diretor).
// Module-level desde o início: guarda o histórico de mensagens como estado
// próprio, e isso teria que sobreviver aos polls de 10s do componente pai —
// exatamente o padrão que já quebrou duas vezes (Feature 2 e 3) quando um
// componente com estado ficou aninhado dentro de outro que é redefinido a
// cada render.
function ChatManutencao({ token, socket }) {
  const [mensagens, setMensagens] = useState([]);
  const [novaMensagem, setNovaMensagem] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [erroChat, setErroChat] = useState(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (!token) return;
    fetch(`${API_URL}/chat/manutencao`, {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then(async (r) => {
        const data = await r.json();
        if (!r.ok) throw new Error(data.erro || 'Erro ao carregar chat');
        setMensagens(data);
      })
      .catch((err) => setErroChat(err.message));
  }, [token]);

  useEffect(() => {
    if (!socket) return;
    const handler = (data) => setMensagens((prev) => [...prev, data]);
    socket.on('chat_msg', handler);
    return () => socket.off('chat_msg', handler);
  }, [socket]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [mensagens]);

  async function enviarMensagem(e) {
    e.preventDefault();
    if (!novaMensagem.trim() || !token) return;
    setEnviando(true);
    setErroChat(null);
    try {
      const res = await fetch(`${API_URL}/chat/manutencao/enviar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ mensagem: novaMensagem })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.erro || 'Erro ao enviar mensagem');
      setNovaMensagem('');
      // O WebSocket já vai trazer essa mesma mensagem de volta via 'chat_msg';
      // não adiciona aqui pra não duplicar na tela.
    } catch (err) {
      setErroChat(err.message);
    } finally {
      setEnviando(false);
    }
  }

  const corRole = { operador: 'var(--azul-medio)', coordenador: 'var(--verde)', gestor: 'var(--amarelo)', diretor: 'var(--vermelho)' };
  const emojiRole = { operador: '🔧', coordenador: '📋', gestor: '📊', diretor: '🏢' };

  function nomeCurto(email) {
    if (!email) return '-';
    const usuario = email.split('@')[0];
    return usuario.charAt(0).toUpperCase() + usuario.slice(1);
  }

  return (
    <div className="chat-manutencao">
      <h2 style={{ marginBottom: 15 }}>Chat — Manutenção</h2>

      {!token && (
        <p style={{ color: 'var(--cinza-texto)', fontSize: 13 }}>
          Faça login para participar do chat.
        </p>
      )}

      <div className="chat-historico">
        {mensagens.length === 0 ? (
          <p className="chat-vazio">Nenhuma mensagem ainda. Comece a conversa!</p>
        ) : (
          mensagens.map((msg) => (
            <div key={msg.id} className="chat-msg">
              <div className="msg-header">
                <span className="msg-role" style={{ color: corRole[msg.role] || 'var(--cinza-texto)' }}>
                  {emojiRole[msg.role] || '👤'} {nomeCurto(msg.usuario)}
                </span>
                <small>{new Date(msg.criado_em).toLocaleTimeString('pt-BR')}</small>
              </div>
              <p className="msg-texto">{msg.mensagem}</p>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      {erroChat && <p style={{ color: 'var(--vermelho)', fontSize: 12 }}>{erroChat}</p>}

      <form onSubmit={enviarMensagem} className="chat-input">
        <input
          type="text"
          value={novaMensagem}
          onChange={(e) => setNovaMensagem(e.target.value)}
          placeholder="Escreva uma mensagem..."
          disabled={enviando || !token}
        />
        <button type="submit" disabled={enviando || !token}>
          {enviando ? 'Enviando...' : '📤 Enviar'}
        </button>
      </form>
    </div>
  );
}

function ModalMaquina({ maquina, token, role, onClose, onUpdate }) {
  // Mesma regra do backend (requer_roles em /quebrada e /consertada, Etapa 0
  // do bot do Telegram): quem não pode fazer a ação nem vê o botão.
  const podeReportarQuebra = role === 'operador' || role === 'coordenador';
  const podeConsertar = role === 'coordenador';
  const [loading, setLoading] = useState(false);
  const [showRelatorio, setShowRelatorio] = useState(false);
  const [relatorio, setRelatorio] = useState('');
  const [erroModal, setErroModal] = useState(null);

  async function handleNotificarQuebra() {
    setLoading(true);
    setErroModal(null);
    try {
      const res = await fetch(`${API_URL}/maquinas/${maquina.id}/quebrada`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.erro || 'Erro ao notificar quebra');
      }
      onUpdate({ ...maquina, status: 'QUEBRADA' });
    } catch (err) {
      setErroModal(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleConsertada() {
    setLoading(true);
    setErroModal(null);
    try {
      const res = await fetch(`${API_URL}/maquinas/${maquina.id}/consertada`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ relatorio })
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.erro || 'Erro ao confirmar conserto');
      }
      onUpdate({ ...maquina, status: 'DISPONIVEL' });
    } catch (err) {
      setErroModal(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>

        <h2>🔧 {maquina.nome}</h2>

        <section className="modal-section">
          {maquina.foto_url && (
            <section className="modal-section">
              <img 
                src={`${BACKEND_URL}/fotos_maquinas/${maquina.foto_url}`}
                alt={maquina.nome}
                style={{ width: '100%', height: 250, objectFit: 'contain', borderRadius: 4, marginBottom: 12 }}
              />
            </section>
          )}
          <p><strong>Local:</strong> {maquina.localizacao || '-'}</p>
          {maquina.modelo && <p><strong>Modelo:</strong> {maquina.modelo}</p>}
          {maquina.fabricante && <p><strong>Fabricante:</strong> {maquina.fabricante}</p>}
          <p><strong>Status:</strong> {maquina.status}</p>
        </section>

        {maquina.manual_url && (
          <section className="modal-section">
            <a href={maquina.manual_url} target="_blank" rel="noreferrer" className="btn-secondary">
              📄 Baixar Manual Técnico
            </a>
          </section>
        )}

        {erroModal && <p style={{ color: 'var(--vermelho)' }}>{erroModal}</p>}

        {!showRelatorio ? (
          <div className="modal-buttons">
            {maquina.status === 'DISPONIVEL' && podeReportarQuebra && (
              <button onClick={handleNotificarQuebra} disabled={loading} className="btn-danger">
                🚨 Notificar Quebra
              </button>
            )}
            {maquina.status !== 'DISPONIVEL' && podeConsertar && (
              <button onClick={() => setShowRelatorio(true)} disabled={loading} className="btn-success">
                ✅ Máquina Consertada
              </button>
            )}
            <button onClick={onClose} className="btn-primary">Fechar</button>
          </div>
        ) : (
          <div className="modal-section">
            <h3>📝 Nota de Relatório</h3>
            <textarea
              value={relatorio}
              onChange={(e) => setRelatorio(e.target.value)}
              placeholder="Descreva o problema, como foi consertado, tempo gasto..."
              style={{ width: '100%', height: 120, fontFamily: 'inherit', fontSize: 13 }}
            />
            <div className="modal-buttons" style={{ marginTop: 15 }}>
              <button onClick={handleConsertada} disabled={loading} className="btn-success">
                ✅ Confirmar Conserto
              </button>
              <button onClick={() => setShowRelatorio(false)} className="btn-secondary">
                ← Voltar
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Feature 3 - Painel de Manutenção de Máquinas.
// Module-level pelo mesmo motivo do ModalMaquina/ModalVerMais: continha
// <ModalMaquina/> como filho, e como PainelManutencao era redefinida a
// cada render do componente pai, o React remontava a árvore inteira
// (inclusive o modal filho, mesmo ele sendo estável) a cada poll de 10s —
// por isso "Nota de Relatório" voltava pro botão sozinho.
function PainelManutencao({ maquinas, token, role, selectedMaquina, setSelectedMaquina, setMaquinas }) {
  const corStatus = { QUEBRADA: 'var(--vermelho)', DISPONIVEL: 'var(--verde)' };
  const emojiStatus = { QUEBRADA: '🔴', DISPONIVEL: '🟢' };

  return (
    <div className="painel">
      <h2 style={{ marginBottom: 20 }}>Manutenção de Máquinas</h2>

      <div className="maquinas-grid">
        {maquinas.map((maq) => (
          <div
            key={maq.id}
            className="card-maquina"
            style={{ borderLeft: `4px solid ${corStatus[maq.status] || 'var(--cinza-borda)'}` }}
            onClick={() => setSelectedMaquina(maq)}
          >
            <h3>{emojiStatus[maq.status] || '⚪'} {maq.nome}</h3>
            <p>📍 {maq.localizacao || '-'}</p>
            {maq.modelo && <p>{maq.modelo}{maq.fabricante ? ` (${maq.fabricante})` : ''}</p>}
            <p>Status: <strong>{maq.status}</strong></p>
          </div>
        ))}
      </div>

      {selectedMaquina && (
        <ModalMaquina
          maquina={selectedMaquina}
          token={token}
          role={role}
          onClose={() => setSelectedMaquina(null)}
          onUpdate={(atualizada) => {
            setMaquinas(prev => prev.map(m => m.id === atualizada.id ? atualizada : m));
            setSelectedMaquina(null);
          }}
        />
      )}
    </div>
  );
}

// Data no formato YYYY-MM-DD em HORA LOCAL. toISOString() devolveria a data em
// UTC, que depois das 21h (UTC-3) já é o dia seguinte.
function dataLocal(d = new Date()) {
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${mm}-${dd}`;
}

// Avisa quando o que está na tela inclui dados gerados por seed_demo.py.
// Não esconde nada, só identifica. Sem estado, mas fica no nível do módulo
// como os outros componentes compartilhados: os painéis de Gestão são
// aninhados em SistemaAutomacao e PainelProgramacao é de módulo.
function AvisoOrigemDados({ origemDados }) {
  if (!origemDados || !origemDados.demonstracao) return null;

  const m = origemDados.demonstracao;
  const n = origemDados.real ?? 0;

  return (
    <div className="aviso-info" role="note" style={{ marginBottom: 16 }}>
      Estes indicadores incluem {m}{' '}
      {m === 1 ? 'registro de demonstração, gerado' : 'registros de demonstração, gerados'} para
      validar o sistema. {n === 1 ? '1 é registro real.' : `${n} são registros reais.`}
    </div>
  );
}

// Fase 3 - Timeline da oficina. Fica NO NÍVEL DO MÓDULO (junto de
// ModalVerMais e PainelManutencao), não dentro de SistemaAutomacao: ele tem
// estado próprio (data, barra em foco) e seria remontado a cada poll de 10s.
function PainelProgramacao({ socket }) {
  const [dados, setDados] = useState(null);
  const [data, setData] = useState(() => dataLocal());
  const [carregando, setCarregando] = useState(true);
  const [erroProg, setErroProg] = useState(null);
  const [foco, setFoco] = useState(null);

  useEffect(() => {
    setCarregando(true);
    setErroProg(null);
    fetch(`${API_URL}/programacao?data=${data}`)
      .then(async (r) => {
        const json = await r.json();
        if (!r.ok) throw new Error(json.erro || 'Erro ao carregar programação');
        setDados(json);
      })
      .catch((e) => setErroProg(e.message))
      .finally(() => setCarregando(false));
  }, [data]);

  // Uma operação iniciada ou concluída (pelo site ou, na Etapa 2, pelo bot do
  // Telegram) muda esta tela sem precisar trocar de dia e voltar. Recarrega
  // o dia em exibição em silêncio, sem passar pelo "Carregando..." de cima.
  useEffect(() => {
    if (!socket) return;
    const recarregar = () => {
      fetch(`${API_URL}/programacao?data=${data}`)
        .then(async (r) => {
          const json = await r.json();
          if (r.ok) setDados(json);
        })
        .catch(() => {});
    };
    const eventos = ['operacao_iniciada', 'operacao_concluida', 'operacao_interrompida',
      'operacao_liberada', 'maquina_quebrada', 'maquina_consertada'];
    eventos.forEach((ev) => socket.on(ev, recarregar));
    return () => eventos.forEach((ev) => socket.off(ev, recarregar));
  }, [socket, data]);

  function mudarDia(dias) {
    const d = new Date(data + 'T12:00:00');
    d.setDate(d.getDate() + dias);
    setData(dataLocal(d));
  }

  const corStatus = {
    PLANEJADO: 'var(--cinza-borda)',
    LIBERADO: 'var(--amarelo)',
    EXECUTANDO: 'var(--azul-medio)',
    CONCLUIDO: 'var(--verde)',
  };

  return (
    <div className="painel">
      <div className="prog-topo">
        <div>
          <h2 style={{ marginBottom: 4 }}>Programação da oficina</h2>
          <p className="prog-sub">
            {dados
              ? `${dados.total_operacoes} operação(ões) entre ${dados.janela_inicio} e ${dados.janela_fim}`
              : 'Carregando...'}
          </p>
        </div>

        <div className="prog-nav">
          <button type="button" className="btn-pequeno" onClick={() => mudarDia(-1)}>
            ← Dia anterior
          </button>
          <input
            type="date"
            value={data}
            onChange={(e) => setData(e.target.value)}
            aria-label="Data da programação"
          />
          <button type="button" className="btn-pequeno" onClick={() => mudarDia(1)}>
            Próximo dia →
          </button>
        </div>
      </div>

      {dados && <AvisoOrigemDados origemDados={dados.origem_dados} />}

      {erroProg && <div className="aviso">{erroProg}</div>}

      {dados && dados.conflitos.length > 0 && (
        <div className="aviso" style={{ marginTop: 0, marginBottom: 16 }}>
          <strong>
            {dados.conflitos.length} conflito(s) de programação
          </strong>
          <ul style={{ listStyle: 'none', marginTop: 8, fontSize: 13 }}>
            {dados.conflitos.map((c, i) => (
              <li key={i} style={{ padding: '3px 0' }}>
                {c.maquina_nome}: {c.os_a} e {c.os_b} se sobrepõem em{' '}
                {c.sobreposicao_min} min
              </li>
            ))}
          </ul>
        </div>
      )}

      {carregando && <p>Carregando programação...</p>}

      {dados && !carregando && (
        <>
          <div className="prog-legenda">
            <span><i style={{ background: corStatus.PLANEJADO }} /> Planejado</span>
            <span><i style={{ background: corStatus.LIBERADO }} /> Liberado</span>
            <span><i style={{ background: corStatus.EXECUTANDO }} /> Executando</span>
            <span><i style={{ background: corStatus.CONCLUIDO }} /> Concluído</span>
            <span><i className="prog-interrompida-leg" /> Interrompida (máquina parada)</span>
            <span><i className="prog-hachura" /> Realizado</span>
            <span><i className="prog-parada-leg" /> Trecho parado</span>
          </div>

          <div className="prog-wrapper">
            <div className="prog-eixo">
              <div className="prog-rotulo-vazio" />
              <div className="prog-marcas">
                {dados.marcas.map((m, i) => (
                  <span key={i} style={{ left: `${m.esquerda_pct}%` }}>
                    {m.hora}
                  </span>
                ))}
              </div>
            </div>

            {dados.maquinas.map((maq) => (
              <div key={maq.id} className="prog-linha">
                <div className={`prog-rotulo ${maq.parada ? 'parada' : ''}`}>
                  <strong>{maq.nome}</strong>
                  <small>{maq.parada ? 'PARADA' : maq.localizacao || '-'}</small>
                </div>

                <div className="prog-faixa">
                  {dados.marcas.map((m, i) => (
                    <div
                      key={i}
                      className="prog-grade"
                      style={{ left: `${m.esquerda_pct}%` }}
                    />
                  ))}

                  {dados.agora_pct !== null && (
                    <div
                      className="prog-agora"
                      style={{ left: `${dados.agora_pct}%` }}
                      title="agora"
                    />
                  )}

                  {maq.barras.map((b) => (
                    <React.Fragment key={b.alocacao_id}>
                      {b.planejado && (
                        <button
                          type="button"
                          className={`prog-barra ${foco === b.alocacao_id ? 'foco' : ''} ${b.status === 'INTERROMPIDA' ? 'interrompida' : ''}`}
                          style={{
                            left: `${b.planejado.esquerda_pct}%`,
                            width: `${b.planejado.largura_pct}%`,
                            ...(b.status === 'INTERROMPIDA'
                              ? {}
                              : { background: corStatus[b.status] || 'var(--cinza-borda)' }),
                          }}
                          onClick={() =>
                            setFoco(foco === b.alocacao_id ? null : b.alocacao_id)
                          }
                          title={`${b.os_numero} · OP ${b.sequencia} · ${b.planejado.inicio}–${b.planejado.fim}`}
                        >
                          <span>{b.os_numero}</span>
                        </button>
                      )}

                      {b.realizado && (
                        <div
                          className="prog-barra-real"
                          style={{
                            left: `${b.realizado.esquerda_pct}%`,
                            width: `${b.realizado.largura_pct}%`,
                          }}
                          title={`realizado ${b.realizado.inicio}–${b.realizado.fim}`}
                        />
                      )}

                      {/* trechos em que a máquina esteve parada, sobre a faixa do realizado */}
                      {(b.paradas || []).map((p, i) => (
                        <div
                          key={`p${i}`}
                          className="prog-barra-parada"
                          style={{ left: `${p.esquerda_pct}%`, width: `${p.largura_pct}%` }}
                          title={`máquina parada ${p.inicio}–${p.aberta ? 'em andamento' : p.fim}`}
                        />
                      ))}
                    </React.Fragment>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {foco && (() => {
            const b = dados.maquinas
              .flatMap((m) => m.barras)
              .find((x) => x.alocacao_id === foco);
            if (!b) return null;
            return (
              <div className="prog-detalhe">
                <h3>{b.os_numero} — operação {b.sequencia}</h3>
                <p><strong>Peça:</strong> {b.peca_nome || b.peca_codigo}</p>
                <p><strong>Status:</strong> {b.status}</p>
                <p>
                  <strong>Planejado:</strong>{' '}
                  {b.planejado
                    ? `${b.planejado.inicio}–${b.planejado.fim} (${b.planejado.minutos} min)`
                    : '—'}
                </p>
                <p>
                  <strong>Realizado:</strong>{' '}
                  {b.realizado
                    ? `${b.realizado.inicio}–${b.realizado.fim} (${b.tempo_realizado_min ?? '—'} min)`
                    : '— ainda não medido'}
                </p>
                <p><strong>Operador:</strong> {b.operador || '—'}</p>
                {b.status === 'INTERROMPIDA' && (
                  <p style={{ color: 'var(--vermelho)' }}>
                    <strong>Interrompida:</strong> a máquina quebrou; {b.tempo_acumulado_min ?? 0} min de usinagem
                    já feitos. Volta a LIBERADO quando o conserto for registrado.
                  </p>
                )}
                {(b.paradas || []).length > 0 && (
                  <p><strong>Paradas:</strong>{' '}
                    {b.paradas.map((p) => `${p.inicio}–${p.aberta ? 'em andamento' : p.fim}`).join(' · ')}</p>
                )}
              </div>
            );
          })()}
        </>
      )}
    </div>
  );
}

export default function SistemaAutomacao() {
  // ============================================================================
  // ESTADO GERAL
  // ============================================================================

  const [tab, setTab] = useState('operador');
  const [modulo, setModulo] = useState('producao');
  const [notas, setNotas] = useState([]);
  const [ordens, setOrdens] = useState([]);
  const [pecas, setPecas] = useState([]);
  const [maquinas, setMaquinas] = useState([]);
  const [metricas, setMetricas] = useState(null);
  const [auditoria, setAuditoria] = useState([]);
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState(null);

  // Feature 2 - Modal "Ver Mais" (detalhes completos da nota)
  const [modalNota, setModalNota] = useState(null);

  // Feature 3 - Manutenção de máquinas
  const [selectedMaquina, setSelectedMaquina] = useState(null);

  // Diferencial #4 - WebSocket tempo real
  const [wsConectado, setWsConectado] = useState(false);
  const [eventosTempoReal, setEventosTempoReal] = useState([]);
  const socketRef = useRef(null);

  // Diferencial #5 - Autenticação JWT
  const [token, setToken] = useState(() => localStorage.getItem('token') || '');
  const [usuarioLogado, setUsuarioLogado] = useState(() => localStorage.getItem('usuario') || '');
  const [role, setRole] = useState(() => localStorage.getItem('role') || '');
  const [loginEmail, setLoginEmail] = useState('operador@fabrica.com');
  const [loginSenha, setLoginSenha] = useState('');
  const [loginErro, setLoginErro] = useState(null);
  const [painelProtegido, setPainelProtegido] = useState(null);

  // Diferencial #1 - Integração SAP
  const [arquivoSap, setArquivoSap] = useState(null);
  const [resultadoSap, setResultadoSap] = useState(null);
  const [carregandoSap, setCarregandoSap] = useState(false);

  // Diferencial #3 - Relatório em PDF
  const MESES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
                 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];
  const [mesRelatorio, setMesRelatorio] = useState(MESES[new Date().getMonth()]);
  const [anoRelatorio, setAnoRelatorio] = useState(new Date().getFullYear());

  // Diferencial #6 - Backup automático
  const [backups, setBackups] = useState([]);
  const [criandoBackup, setCriandoBackup] = useState(false);

  // Diferencial #10 - Estatísticas customizadas
  const [estatisticas, setEstatisticas] = useState(null);

  // ============================================================================
  // EFEITOS (Carregar dados iniciais e atualizar)
  // ============================================================================

  useEffect(() => {
    carregarDados();
    const intervalo = setInterval(carregarDados, 10000); // Atualizar a cada 10s
    return () => clearInterval(intervalo);
  }, []);

  // Carrega os dados de Backup e Estatísticas quando a tela é aberta,
  // uma vez por abertura. Antes esses fetch ficavam dentro dos painéis,
  // que são recriados a cada render — o efeito disparava a cada poll.
  useEffect(() => {
    if (tab === 'backup') carregarBackups();
    if (tab === 'estatisticas' && telaPermitida('estatisticas')) carregarEstatisticas();
  }, [tab]);

  // Diferencial #4 - conecta ao WebSocket uma única vez
  useEffect(() => {
    const socket = io(SOCKET_URL, { transports: ['websocket', 'polling'] });
    socketRef.current = socket;

    socket.on('connect', () => setWsConectado(true));
    socket.on('disconnect', () => setWsConectado(false));

    socket.on('status', (data) => {
      setEventosTempoReal(prev => [{ tipo: 'status', ...data, hora: new Date().toLocaleTimeString('pt-BR') }, ...prev].slice(0, 10));
    });

    socket.on('nota_processada', (data) => {
      setEventosTempoReal(prev => [{ tipo: 'nota_processada', ...data, hora: new Date().toLocaleTimeString('pt-BR') }, ...prev].slice(0, 10));
      carregarDados(); // atualiza as tabelas assim que o backend processa algo
    });

    // Feature 3 - Manutenção: atualiza o status da máquina na hora, sem
    // esperar o próximo poll de 10s
    socket.on('maquina_quebrada', (data) => {
      setEventosTempoReal(prev => [{ tipo: 'maquina_quebrada', ...data, hora: new Date().toLocaleTimeString('pt-BR') }, ...prev].slice(0, 10));
      setMaquinas(prev => prev.map(m => m.id === data.id ? { ...m, status: data.status } : m));
    });

    socket.on('maquina_consertada', (data) => {
      setEventosTempoReal(prev => [{ tipo: 'maquina_consertada', ...data, hora: new Date().toLocaleTimeString('pt-BR') }, ...prev].slice(0, 10));
      setMaquinas(prev => prev.map(m => m.id === data.id ? { ...m, status: data.status } : m));
    });

    return () => socket.disconnect();
  }, []);

  async function carregarDados() {
    try {
      const [notasRes, ordensRes, pecasRes, maquinasRes, metricasRes, auditoriaRes] = await Promise.all([
        fetch(`${API_URL}/notas`),
        fetch(`${API_URL}/ordens-servico`),
        fetch(`${API_URL}/pecas`),
        fetch(`${API_URL}/maquinas`),
        fetch(`${API_URL}/metricas`),
        fetch(`${API_URL}/auditoria`),
      ]);

      setNotas(await notasRes.json());
      setOrdens(await ordensRes.json());
      setPecas(await pecasRes.json());
      setMaquinas(await maquinasRes.json());
      setMetricas(await metricasRes.json());
      setAuditoria(await auditoriaRes.json());
    } catch (e) {
      setErro('Erro ao carregar dados');
      console.error(e);
    }
  }

  // ============================================================================
  // AÇÕES
  // ============================================================================

  async function criarNota(peca_codigo, quantidade = 1, prioridade = 'NORMAL') {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/notas`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ peca_codigo, quantidade, prioridade, solicitante: 'TESTE' })
      });

      const resultado = await res.json();
      alert(`Nota criada: ${resultado.numero}\nOS: ${resultado.processamento.os_numero}`);
      await carregarDados();
    } catch (e) {
      alert('Erro ao criar nota');
    } finally {
      setLoading(false);
    }
  }

  async function iniciarOrdem(os_id) {
    try {
      const res = await fetch(`${API_URL}/ordens-servico/${os_id}/iniciar`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) {
        const erro = await res.json().catch(() => ({}));
        alert(erro.erro || erro.msg || 'Erro ao iniciar ordem');
        return;
      }
      await carregarDados();
    } catch (e) {
      alert('Erro ao iniciar ordem');
    }
  }

  // --- Diferencial #5: Autenticação JWT -------------------------------------

  async function fazerLogin(e) {
    e.preventDefault();
    setLoginErro(null);
    try {
      const res = await fetch(`${API_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: loginEmail, senha: loginSenha })
      });
      const data = await res.json();
      if (!res.ok) {
        setLoginErro(data.erro || 'Falha no login');
        return;
      }
      setToken(data.token);
      setUsuarioLogado(data.usuario);
      setRole(data.role);
      localStorage.setItem('token', data.token);
      localStorage.setItem('usuario', data.usuario);
      localStorage.setItem('role', data.role);
      setPainelProtegido(null);
    } catch (e) {
      setLoginErro('Erro de conexão com o backend');
    }
  }

  function sair() {
    setToken('');
    setUsuarioLogado('');
    setRole('');
    setPainelProtegido(null);
    localStorage.removeItem('token');
    localStorage.removeItem('usuario');
    localStorage.removeItem('role');
  }

  async function carregarPainelProtegido() {
    const rota = role === 'gestor' || role === 'diretor' ? 'gestor' : 'operador';
    try {
      const res = await fetch(`${API_URL}/painel/${rota}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (!res.ok) {
        setPainelProtegido({ erro: data.erro || 'Acesso negado' });
        return;
      }
      setPainelProtegido(data);
    } catch (e) {
      setPainelProtegido({ erro: 'Erro de conexão com o backend' });
    }
  }

  // --- Diferencial #1: Integração SAP ----------------------------------------

  async function importarSap() {
    if (!arquivoSap) return;
    setCarregandoSap(true);
    setResultadoSap(null);
    try {
      const formData = new FormData();
      formData.append('arquivo', arquivoSap);
      const res = await fetch(`${API_URL}/sap/importar`, { method: 'POST', body: formData });
      const data = await res.json();
      setResultadoSap(data);
      await carregarDados();
    } catch (e) {
      setResultadoSap({ sucesso: false, erro: 'Erro ao importar arquivo' });
    } finally {
      setCarregandoSap(false);
    }
  }

  // --- Diferencial #3: Relatório em PDF ---------------------------------------

  function baixarRelatorioPdf() {
    const url = `${API_URL}/relatorio/economia?mes=${encodeURIComponent(mesRelatorio)}&ano=${anoRelatorio}`;
    window.open(url, '_blank');
  }

  // --- Diferencial #6: Backup automático --------------------------------------

  async function carregarBackups() {
    try {
      const res = await fetch(`${API_URL}/backup/listar`);
      setBackups(await res.json());
    } catch (e) {
      console.error(e);
    }
  }

  async function criarBackup() {
    setCriandoBackup(true);
    try {
      await fetch(`${API_URL}/backup/criar`, { method: 'POST' });
      await carregarBackups();
    } catch (e) {
      alert('Erro ao criar backup');
    } finally {
      setCriandoBackup(false);
    }
  }

  // --- Diferencial #10: Estatísticas customizadas -----------------------------

  async function carregarEstatisticas() {
    try {
      const res = await fetch(`${API_URL}/estatisticas`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      });
      if (!res.ok) { setEstatisticas(null); return; }
      setEstatisticas(await res.json());
    } catch (e) {
      console.error(e);
    }
  }

  // ============================================================================
  // COMPONENTES
  // ============================================================================

  // Painel OPERADOR
  function PainelOperador() {
    return (
      <div className="painel">
        <h2 style={{ marginBottom: 20 }}>Fila de Trabalho</h2>
        <div className="tabela-wrapper">
          <table>
            <thead>
              <tr>
                <th>OS</th>
                <th>Peça</th>
                <th>Máquina</th>
                <th>Tempo</th>
                <th>Prioridade</th>
                <th>Status</th>
                <th>Ação</th>
              </tr>
            </thead>
            <tbody>
              {ordens.map(ordem => (
                <tr key={ordem.id}>
                  <td><strong>{ordem.numero}</strong></td>
                  <td>{ordem.peca_nome}</td>
                  <td>-</td>
                  <td>{ordem.tempo_total} min</td>
                  <td><span className={ordem.prioridade === 'URGENTE' ? 'badge-urgente' : 'badge-normal'}>{ordem.prioridade}</span></td>
                  <td><span className="status-badge">{ordem.status}</span></td>
                  <td>
                    {ordem.status === 'PLANEJAMENTO' && (role === 'operador' || role === 'coordenador') && (
                      <button onClick={() => iniciarOrdem(ordem.id)} className="btn-pequeno">Iniciar</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  // Painel GESTÃO
  function PainelGestao() {
    if (!metricas) return <div>Carregando...</div>;

    return (
      <div className="painel">
        <h2 style={{ marginBottom: 20 }}>Métricas e Impacto</h2>

        <AvisoOrigemDados origemDados={metricas.origem_dados} />

        <div className="cards-grid">
          <div className="card-metrica">
            <div className="metrica-icon">📊</div>
            <div className="metrica-label">Total de OS</div>
            <div className="metrica-valor">{ordens.length}</div>
          </div>
          <div className="card-metrica">
            <div className="metrica-icon">✅</div>
            <div className="metrica-label">Concluídas</div>
            <div className="metrica-valor">{metricas.os_concluidas}</div>
          </div>
          <div className="card-metrica">
            <div className="metrica-icon">⏰</div>
            <div className="metrica-label">Taxa Aderência</div>
            <div className="metrica-valor">{metricas.taxa_aderencia}%</div>
          </div>
          <div className="card-metrica">
            <div className="metrica-icon">💰</div>
            <div className="metrica-label">Economia/Mês</div>
            <div className="metrica-valor">R$ {metricas.economia_mensal.toFixed(0)}</div>
          </div>
        </div>

        <div className="tabela-wrapper" style={{ marginTop: 30 }}>
          <h3>Impacto: ANTES vs DEPOIS</h3>
          <table>
            <thead>
              <tr>
                <th>Métrica</th>
                <th>❌ SEM Sistema</th>
                <th>✅ COM Sistema</th>
                <th>Melhoria</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>Tempo/Nota</strong></td>
                <td>45 min</td>
                <td>3 min</td>
                <td style={{ color: 'var(--verde)' }}>93% ⬇️</td>
              </tr>
              <tr>
                <td><strong>Taxa de Erro</strong></td>
                <td>28%</td>
                <td>0%</td>
                <td style={{ color: 'var(--verde)' }}>100% ⬇️</td>
              </tr>
              <tr>
                <td><strong>Custo Retrabalho</strong></td>
                <td>R$ 890/sem</td>
                <td>R$ 0</td>
                <td style={{ color: 'var(--verde)' }}>Eliminado</td>
              </tr>
              <tr>
                <td><strong>Horas Extras</strong></td>
                <td>5h/sem</td>
                <td>0.5h/sem</td>
                <td style={{ color: 'var(--verde)' }}>90% ⬇️</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  function PainelNotas() {
    return (
      <div className="painel">
        <h2 style={{ marginBottom: 20 }}>Criar Nova Nota</h2>

        <div className="form-grupo">
          <label>Selecione uma peça:</label>
          <div className="botoes-grupo">
            {pecas.map(peca => (
              <button
                key={peca.id}
                className="btn-nota"
                onClick={() => criarNota(peca.codigo, 1, 'NORMAL')}
                disabled={loading}
              >
                {peca.nome}
              </button>
            ))}
          </div>
        </div>

        <div className="form-grupo" style={{ marginTop: 20 }}>
          <label>Ou criar nota urgente:</label>
          <div className="botoes-grupo">
            {pecas.map(peca => (
              <button
                key={peca.id}
                className="btn-urgente"
                onClick={() => criarNota(peca.codigo, 1, 'URGENTE')}
                disabled={loading}
              >
                🚨 {peca.nome} (URGENTE)
              </button>
            ))}
          </div>
        </div>

        <div className="tabela-wrapper" style={{ marginTop: 30 }}>
          <h3>Histórico de Notas</h3>
          <table>
            <thead>
              <tr>
                <th>Nº Nota</th>
                <th>Peça</th>
                <th>Qtd</th>
                <th>Prioridade</th>
                <th>Status</th>
                <th>Criada</th>
                <th>Ação</th>
              </tr>
            </thead>
            <tbody>
              {notas.map(nota => (
                <tr key={nota.id}>
                  <td><strong>{nota.numero}</strong></td>
                  <td>{nota.peca_codigo}</td>
                  <td>{nota.quantidade}</td>
                  <td><span className={nota.prioridade === 'URGENTE' ? 'badge-urgente' : 'badge-normal'}>{nota.prioridade}</span></td>
                  <td><span className="status-badge">{nota.status}</span></td>
                  <td>{new Date(nota.criada_em).toLocaleString('pt-BR')}</td>
                  <td>
                    <button onClick={() => setModalNota(nota.id)} className="btn-pequeno">Ver Mais</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {modalNota && (
          <ModalVerMais notaId={modalNota} token={token} onClose={() => setModalNota(null)} />
        )}
      </div>
    );
  }

  // Painel AUDITORIA
  function PainelAuditoria() {
    return (
      <div className="painel">
        <h2 style={{ marginBottom: 20 }}>Auditoria e Rastreamento</h2>

        <div className="tabela-wrapper">
          <table>
            <thead>
              <tr>
                <th>Hora</th>
                <th>Evento</th>
                <th>Entidade</th>
                <th>Descrição</th>
              </tr>
            </thead>
            <tbody>
              {auditoria.map(evento => (
                <tr key={evento.id}>
                  <td>{new Date(evento.criado_em).toLocaleTimeString('pt-BR')}</td>
                  <td><strong>{evento.tipo_evento}</strong></td>
                  <td>{evento.entidade}</td>
                  <td>{evento.descricao}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  // Painel SAP (Diferencial #1)
  function PainelSap() {
    return (
      <div className="painel">
        <h2 style={{ marginBottom: 20 }}>Importação SAP</h2>
        <p style={{ marginBottom: 20, color: 'var(--cinza-texto)' }}>
          Envie um arquivo SAP (tab-separated) com as colunas NOTNUM, MATERIAL, QTD, DUEDATE, URGENTE.
        </p>

        <div className="form-grupo">
          <input
            type="file"
            accept=".txt"
            onChange={(e) => setArquivoSap(e.target.files[0])}
          />
          <button
            className="btn-nota"
            style={{ marginLeft: 12, width: 'auto', padding: '12px 24px' }}
            onClick={importarSap}
            disabled={!arquivoSap || carregandoSap}
          >
            {carregandoSap ? 'Importando...' : 'Importar Arquivo'}
          </button>
        </div>

        {resultadoSap && (
          <div style={{ marginTop: 24 }}>
            <p><strong>Sucesso:</strong> {String(resultadoSap.sucesso)}</p>
            <p><strong>Total processadas:</strong> {resultadoSap.total_processadas}</p>
            <p><strong>Tempo de processamento:</strong> {resultadoSap.tempo_processamento}</p>

            {resultadoSap.erros && resultadoSap.erros.length > 0 && (
              <div style={{ marginTop: 12, background: '#F8D7DA', border: '1px solid #F5C6CB', color: '#721C24', padding: 16, borderRadius: 4 }}>
                <strong>Erros de validação:</strong>
                <ul>
                  {resultadoSap.erros.map((erro, i) => <li key={i}>{erro}</li>)}
                </ul>
              </div>
            )}

            {resultadoSap.notas && (
              <div className="tabela-wrapper" style={{ marginTop: 20 }}>
                <table>
                  <thead>
                    <tr>
                      <th>Nota SAP</th>
                      <th>Material</th>
                      <th>Qtd</th>
                      <th>Peça encontrada</th>
                      <th>OS gerada</th>
                      <th>Tempo (min)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {resultadoSap.notas.map((n, i) => (
                      <tr key={i}>
                        <td>{n.numero}</td>
                        <td>{n.material}</td>
                        <td>{n.quantidade}</td>
                        <td>{n.peca_encontrada ? '✅' : '❌'}</td>
                        <td>{n.os_numero || '-'}</td>
                        <td>{n.tempo_total_minutos}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  // Painel RELATÓRIO PDF (Diferencial #3)
  function PainelRelatorio() {
    return (
      <div className="painel">
        <h2 style={{ marginBottom: 20 }}>Relatório de Economia (PDF)</h2>

        <div className="form-grupo" style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <select value={mesRelatorio} onChange={(e) => setMesRelatorio(e.target.value)}>
            {MESES.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          <input
            type="number"
            value={anoRelatorio}
            onChange={(e) => setAnoRelatorio(e.target.value)}
            style={{ width: 100 }}
          />
          <button className="btn-nota" style={{ width: 'auto', padding: '12px 24px' }} onClick={baixarRelatorioPdf}>
            Baixar PDF
          </button>
        </div>
        <p style={{ marginTop: 16, color: 'var(--cinza-texto)' }}>
          Abre o PDF gerado pelo backend em uma nova aba, com a economia calculada a partir do banco de dados real.
        </p>
      </div>
    );
  }

  // Painel BACKUP (Diferencial #6)
  function PainelBackup() {
    return (
      <div className="painel">
        <h2 style={{ marginBottom: 20 }}>Backup do Banco de Dados</h2>

        <button className="btn-nota" style={{ width: 'auto', padding: '12px 24px' }} onClick={criarBackup} disabled={criandoBackup}>
          {criandoBackup ? 'Criando...' : 'Criar Backup Agora'}
        </button>

        <div className="tabela-wrapper" style={{ marginTop: 24 }}>
          <table>
            <thead>
              <tr>
                <th>Arquivo</th>
                <th>Tamanho (KB)</th>
                <th>Criado em</th>
              </tr>
            </thead>
            <tbody>
              {backups.map((b, i) => (
                <tr key={i}>
                  <td>{b.arquivo}</td>
                  <td>{b.tamanho_kb}</td>
                  <td>{new Date(b.criado_em).toLocaleString('pt-BR')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  // Painel ESTATÍSTICAS (Diferencial #10)
  function PainelEstatisticas() {
    if (!estatisticas) return <div className="painel">Carregando...</div>;

    return (
      <div className="painel">
        <h2 style={{ marginBottom: 20 }}>Estatísticas Customizadas</h2>

        <AvisoOrigemDados origemDados={estatisticas.origem_dados} />

        <h3>Desempenho por máquina</h3>
        <div className="tabela-wrapper" style={{ marginBottom: 24 }}>
          <table>
            <thead><tr><th>Máquina</th><th>Operações</th><th>Tempo planejado (min)</th><th>Tempo realizado (min)</th><th>Operações medidas</th></tr></thead>
            <tbody>
              {estatisticas.desempenho_por_maquina.map((m, i) => (
                <tr key={i}>
                  <td>{m.maquina}</td>
                  <td>{m.operacoes}</td>
                  <td>{m.tempo_planejado_medio_min ?? '—'}</td>
                  <td>{m.tempo_realizado_medio_min ?? '—'}</td>
                  <td>{m.operacoes_medidas}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h3>Notas por solicitante</h3>
        <div className="tabela-wrapper" style={{ marginBottom: 24 }}>
          <table>
            <thead><tr><th>Solicitante</th><th>Total de notas</th><th>Pendentes</th></tr></thead>
            <tbody>
              {estatisticas.notas_por_operador.map((o, i) => (
                <tr key={i}><td>{o.operador}</td><td>{o.total_notas}</td><td>{o.pendentes}</td></tr>
              ))}
            </tbody>
          </table>
        </div>

        <h3>Economia semanal (ano atual)</h3>
        <div className="tabela-wrapper">
          <table>
            <thead><tr><th>Semana</th><th>Notas processadas</th><th>Economia estimada</th></tr></thead>
            <tbody>
              {estatisticas.economia_semanal.map((s, i) => (
                <tr key={i}><td>{s.semana}</td><td>{s.notas_processadas}</td><td>R$ {s.economia_estimada.toFixed(2)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  // Painel LOGIN / ÁREA PROTEGIDA (Diferencial #5)
  function PainelLogin() {
    return (
      <div className="painel">
        <h2 style={{ marginBottom: 20 }}>Login e Área Protegida</h2>

        {!token ? (
          <form onSubmit={fazerLogin} className="form-grupo" style={{ maxWidth: 360 }}>
            <label>Email</label>
            <input value={loginEmail} onChange={(e) => setLoginEmail(e.target.value)} style={{ width: '100%', padding: 10, marginBottom: 12 }} />
            <label>Senha</label>
            <input type="password" value={loginSenha} onChange={(e) => setLoginSenha(e.target.value)} style={{ width: '100%', padding: 10, marginBottom: 12 }} />
            <button className="btn-nota" type="submit" style={{ width: 'auto', padding: '12px 24px' }}>Entrar</button>
            {loginErro && <p style={{ color: 'var(--vermelho)', marginTop: 12 }}>{loginErro}</p>}
            <p style={{ marginTop: 16, color: 'var(--cinza-texto)', fontSize: 13 }}>
              Usuários demo: operador@fabrica.com / coordenador@fabrica.com / gestor@fabrica.com / diretor@fabrica.com — senha Vitor367
            </p>
          </form>
        ) : (
          <div>
            <p>Logado como <strong>{usuarioLogado}</strong> — papel: <strong>{role}</strong></p>
            <button className="btn-pequeno" style={{ marginTop: 12 }} onClick={sair}>Sair</button>

            <div style={{ marginTop: 24 }}>
              <button className="btn-nota" style={{ width: 'auto', padding: '12px 24px' }} onClick={carregarPainelProtegido}>
                Carregar painel protegido ({role})
              </button>
              {painelProtegido && (
                <pre style={{ marginTop: 16, background: 'var(--cinza-bg)', border: '1px solid var(--cinza-borda)', padding: 16, borderRadius: 4, overflowX: 'auto' }}>
                  {JSON.stringify(painelProtegido, null, 2)}
                </pre>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }

  // Telas com `papeis` só aparecem (e só carregam) para esses papéis.
  function telaPermitida(telaId) {
    const t = MODULOS.flatMap((m) => m.telas).find((x) => x.id === telaId);
    return !t || !t.papeis || t.papeis.includes(role);
  }

  // Trocar de módulo leva para a primeira tela dele.
  function abrirModulo(moduloId) {
    const m = MODULOS.find((x) => x.id === moduloId);
    if (!m) return;
    setModulo(moduloId);
    setTab(m.telas[0].id);
  }

  // ============================================================================
  // RENDER PRINCIPAL
  // ============================================================================

  return (
    <div className="container">

      <div className="header">
        <div>
          <h1>Sistema de Automação de Usinagem</h1>
          <p>Grand Prix SENAI 2025 | Pentágono Mecânico</p>
        </div>
        <div className="ws-indicador">
          <span className="ws-bolinha" style={{ background: wsConectado ? 'var(--verde)' : '#adb5bd' }}></span>
          {wsConectado ? 'Tempo real conectado' : 'Tempo real desconectado'}
        </div>
      </div>

      {eventosTempoReal.length > 0 && (
        <div className="feed-tempo-real">
          <strong>🔴 Ao vivo (WebSocket)</strong>
          <ul>
            {eventosTempoReal.map((ev, i) => (
              <li key={i}>
                [{ev.hora}] {
                  ev.tipo === 'nota_processada'
                    ? `OS ${ev.os} criada — peça ${ev.peca}, ${ev.tempo_processamento} min, prioridade ${ev.prioridade}`
                    : ev.tipo === 'maquina_quebrada'
                    ? `🚨 Máquina ${ev.nome} quebrou (${ev.localizacao || '-'})`
                    : ev.tipo === 'maquina_consertada'
                    ? `✅ Máquina ${ev.nome} consertada, voltou a operar`
                    : ev.mensagem
                }
              </li>
            ))}
          </ul>
        </div>
      )}

      {(() => {
        const moduloAtual = MODULOS.find((m) => m.id === modulo) || MODULOS[0];
        const telasVisiveis = moduloAtual.telas.filter((t) => telaPermitida(t.id));
        const temSubmenu = telasVisiveis.length > 1;

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
                {telasVisiveis.map((t) => (
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

      {tab === 'operador' && <PainelOperador />}
      {tab === 'gestao' && <PainelGestao />}
      {tab === 'notas' && <PainelNotas />}
      {tab === 'auditoria' && <PainelAuditoria />}
      {tab === 'sap' && <PainelSap />}
      {tab === 'relatorio' && <PainelRelatorio />}
      {tab === 'backup' && <PainelBackup />}
      {tab === 'estatisticas' && telaPermitida('estatisticas') && <PainelEstatisticas />}
      {tab === 'programacao' && <PainelProgramacao socket={socketRef.current} />}
      {tab === 'busca' && <BuscaOS token={token} />}
      {tab === 'catalogo' && <CatalogoPecas />}
      {tab === 'login' && <PainelLogin />}
      {/* Fora do PainelLogin (aninhado, remonta a cada poll de 10s e perderia o código e a contagem). */}
      {tab === 'login' && token && (
        <div className="painel"><VinculoTelegram token={token} /></div>
      )}
      {tab === 'manutencao' && (
        <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 500px' }}>
            <PainelManutencao
              maquinas={maquinas}
              token={token}
              role={role}
              selectedMaquina={selectedMaquina}
              setSelectedMaquina={setSelectedMaquina}
              setMaquinas={setMaquinas}
            />
          </div>
          <div style={{ flex: '1 1 320px', maxWidth: 380 }}>
            <ChatManutencao token={token} socket={socketRef.current} />
          </div>
        </div>
      )}

      {erro && <div style={{ background: '#F8D7DA', border: '1px solid #F5C6CB', color: '#721C24', padding: 20, borderRadius: 4, marginTop: 20 }}>{erro}</div>}
    </div>
  );
}
