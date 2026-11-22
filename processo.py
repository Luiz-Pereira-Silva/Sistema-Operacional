"""Processo (PCB): campos de memória (etapa 4), segurança e CPU (etapa 5).

`super_bloco.processos` e as funções `criar_processo` / `encerrar_processo`
são o ponto de integração entre as etapas. Os campos de CPU são preenchidos
por comandos_cpu.py quando o processo é criado com --burst.
"""

TIPOS_VALIDOS = ("critical", "normal")


class Processo:
    def __init__(self, pid, nome, tamanho, tipo):
        self.pid = pid
        self.nome = nome
        self.tamanho = tamanho          # em bytes
        self.tipo = tipo                # "critical" ou "normal"
        # --- atributos de memória (preenchidos pelo GerenciadorMemoria) ---
        self.base = None                # critical: endereço inicial na área reservada
        self.tabela_paginas = None      # normal: lista de entradas de página
        # --- segurança (preenchido quando existe sessão; uid 0 = root/kernel) ---
        self.dono_uid = 0
        # --- CPU (etapa 5): preenchido por comandos_cpu.criar_processo_cpu ---
        self.prioridade = None
        self.burst = None               # None = processo só de memória (fora do escalonador)
        self.estado = "PRONTO"
        self.unidades = []              # thread principal + threads extras (escalonador.Unidade)
        self.memoria_liberada = False

    def __repr__(self):
        return f"Processo(pid={self.pid}, nome={self.nome}, tipo={self.tipo}, tamanho={self.tamanho})"


def buscar_processo(super_bloco, nome):
    for processo in super_bloco.processos.values():
        if processo.nome == nome:
            return processo
    return None


def obter_processo(super_bloco, nome):
    processo = buscar_processo(super_bloco, nome)
    if processo is None:
        raise ValueError(f"Processo '{nome}' inexistente")
    return processo


def criar_processo(super_bloco, nome, tamanho, tipo, dono_uid=0):
    if tipo not in TIPOS_VALIDOS:
        raise ValueError("Tipo de processo inválido (use critical ou normal)")
    if buscar_processo(super_bloco, nome) is not None:
        raise ValueError(f"Já existe um processo chamado '{nome}'")

    processo = Processo(super_bloco.proximo_pid, nome, tamanho, tipo)
    processo.dono_uid = dono_uid
    super_bloco.memoria.alocar(processo)      # levanta ValueError se não couber
    super_bloco.processos[processo.pid] = processo
    super_bloco.proximo_pid += 1
    return processo


def encerrar_processo(super_bloco, nome):
    processo = obter_processo(super_bloco, nome)
    cpu = getattr(super_bloco, "cpu", None)
    if cpu is not None:
        cpu.remover_processo(processo)            # sai das filas e solta mutexes
    if processo.memoria_liberada:                 # já liberada ao concluir na simulação
        print(f"[ENCERRAMENTO] Processo '{processo.nome}' já havia concluído; removido da tabela de processos.")
    else:
        super_bloco.memoria.liberar(processo)
    del super_bloco.processos[processo.pid]
