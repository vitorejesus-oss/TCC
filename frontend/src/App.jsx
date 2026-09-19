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
                    <li key={i}>{a.sequencia}. {a.maquina_nome} — {a.status}</li>
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

function ModalMaquina({ maquina, token, onClose, onUpdate }) {
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
            {maquina.status === 'DISPONIVEL' ? (
              <button onClick={handleNotificarQuebra} disabled={loading} className="btn-danger">
                🚨 Notificar Quebra
              </button>
            ) : (
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
function PainelManutencao({ maquinas, token, selectedMaquina, setSelectedMaquina, setMaquinas }) {
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
  const [loginSenha, setLoginSenha] = useState('Vitor367');
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
    if (tab === 'estatisticas') carregarEstatisticas();
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
      const res = await fetch(`${API_URL}/estatisticas`);
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
                    {ordem.status === 'PLANEJAMENTO' && (
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

      {tab === 'operador' && <PainelOperador />}
      {tab === 'gestao' && <PainelGestao />}
      {tab === 'notas' && <PainelNotas />}
      {tab === 'auditoria' && <PainelAuditoria />}
      {tab === 'sap' && <PainelSap />}
      {tab === 'relatorio' && <PainelRelatorio />}
      {tab === 'backup' && <PainelBackup />}
      {tab === 'estatisticas' && <PainelEstatisticas />}
      {tab === 'login' && <PainelLogin />}
      {tab === 'manutencao' && (
        <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 500px' }}>
            <PainelManutencao
              maquinas={maquinas}
              token={token}
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
