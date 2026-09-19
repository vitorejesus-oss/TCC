"""Remove do usinagem.db as notas importadas do SAP e tudo que depende delas.

Apaga as notas cujo numero começa com 'SAP-', as ordens_servico ligadas a
elas e as alocacao_maquinas dessas ordens. Rode antes do pytest: o
test_importar_sap_arquivo precisa que essas notas ainda não existam.
"""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'usinagem.db')


def limpar_sap(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    try:
        c = conn.cursor()
        ids_notas = "SELECT id FROM notas WHERE numero LIKE 'SAP-%'"
        ids_os = f"SELECT id FROM ordens_servico WHERE nota_id IN ({ids_notas})"

        # Ordem: filhos primeiro (o SQLite não força as FKs aqui).
        c.execute(f"DELETE FROM alocacao_maquinas WHERE ordem_servico_id IN ({ids_os})")
        alocacoes = c.rowcount
        c.execute(f"DELETE FROM ordens_servico WHERE nota_id IN ({ids_notas})")
        ordens = c.rowcount
        c.execute("DELETE FROM notas WHERE numero LIKE 'SAP-%'")
        notas = c.rowcount

        conn.commit()
        return notas, ordens, alocacoes
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    notas, ordens, alocacoes = limpar_sap()
    print(f'Removidas: {notas} notas SAP, {ordens} ordens de serviço, '
          f'{alocacoes} alocações de máquina')
