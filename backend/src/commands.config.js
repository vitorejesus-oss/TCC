/**
 * Lista de comandos remotos permitidos ("whitelist").
 *
 * IMPORTANTE (segurança):
 * - NUNCA permita que o app envie um comando de texto livre para ser executado.
 * - Cada comando aqui é pré-definido pelo administrador do servidor, com uma
 *   chave (key) fixa. O app mobile só pode pedir para executar uma dessas
 *   chaves — nunca um comando arbitrário.
 * - Ajuste os comandos abaixo para o que faz sentido no SEU servidor.
 * - "adminOnly: true" restringe o comando a usuários com role "admin".
 */

module.exports = [
  {
    key: 'status',
    label: 'Ver status detalhado',
    description: 'Mostra uptime do sistema operacional',
    cmd: 'uptime',
    adminOnly: false,
  },
  {
    key: 'disk_usage',
    label: 'Uso de disco',
    description: 'Mostra o espaço em disco utilizado',
    cmd: 'df -h',
    adminOnly: false,
  },
  {
    key: 'list_processes',
    label: 'Processos que mais consomem memória',
    description: 'Lista os 10 processos que mais usam memória',
    cmd: "ps aux --sort=-%mem | head -n 11",
    adminOnly: true,
  },
  {
    key: 'restart_app_service',
    label: 'Reiniciar serviço da aplicação',
    description: 'Exemplo: reinicia um serviço systemd chamado "minha-app" (ajuste o nome!)',
    // Troque "minha-app" pelo nome real do seu serviço systemd.
    // O usuário do processo Node precisa ter permissão de sudo sem senha
    // apenas para este comando específico (veja o README, seção "sudoers").
    cmd: 'sudo systemctl restart minha-app',
    adminOnly: true,
  },
];
