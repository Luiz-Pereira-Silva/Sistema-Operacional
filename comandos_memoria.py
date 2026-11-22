"""Comandos de memória/processos e integração com a segurança.

O interpretador só conhece duas coisas deste módulo: `iniciar_memoria`
(no Super_bloco) e `tratar` (despacho dos comandos). Todo o resto da etapa de
memória fica aqui, para não colidir com a etapa de segurança.

Integração com a segurança (por "duck typing", sem importar seguranca.py):
  * se o Super_bloco tem `sessao`, os comandos críticos exigem modo kernel,
    cada processo guarda o uid do dono e as negações vão para o log;
  * se não tem (segurança ainda fora da main), tudo roda como root.
Quando a segurança entrar na main, nada aqui precisa ser alterado.
"""

import processo as proc
import comandos_cpu as cpu_cmd
from memoria import GerenciadorMemoria, NUM_MOLDURAS, parse_tamanho

COMANDOS = {
    "create_process", "terminate_process", "memory_status",
    "memory_compact", "translate_address", "execute_step", "set_replacement",
}


# ------------------------------------------------------------ inicialização
def iniciar_memoria(super_bloco, num_molduras=None):
    """Chamado no fim de Super_bloco.__init__ (depois do GerenciadorIO)."""
    super_bloco.processos = {}       # pid -> Processo
    super_bloco.proximo_pid = 101    # PIDs a partir de 101, como nos exemplos
    super_bloco.memoria = GerenciadorMemoria(
        super_bloco.gerenciador_io, super_bloco.processos,
        NUM_MOLDURAS if num_molduras is None else num_molduras)
    cpu_cmd.iniciar_cpu(super_bloco)             # etapa 5 (CPU/escalonador)


# --------------------------------------------------------------- argumentos
def parse_flags(argumentos):
    """['--name', 'X', '--reserved'] -> {'name': 'X', 'reserved': True}"""
    opcoes = {}
    i = 0
    while i < len(argumentos):
        if not argumentos[i].startswith("--"):
            raise ValueError(f"Argumento inesperado: {argumentos[i]}")
        chave = argumentos[i][2:]
        if i + 1 < len(argumentos) and not argumentos[i + 1].startswith("--"):
            opcoes[chave] = argumentos[i + 1]
            i += 2
        else:
            opcoes[chave] = True
            i += 1
    return opcoes


def exigir(opcoes, *chaves):
    for chave in chaves:
        if not isinstance(opcoes.get(chave), str):
            raise ValueError(f"Parâmetro obrigatório ausente: --{chave}")


# ---------------------------------------------------------------- segurança
def _sessao(super_bloco):
    return getattr(super_bloco, "sessao", None)


def _registrar_negacao(sessao, operacao):
    log = getattr(sessao, "log", None)
    if log is not None:
        log.append(f"{sessao.usuario.nome} negado: {operacao}")


def exigir_kernel(super_bloco, operacao):
    """Sem sessão (segurança ausente) não há restrição."""
    sessao = _sessao(super_bloco)
    if sessao is None:
        return
    try:
        sessao.exigir_kernel(operacao)
    except Exception:
        _registrar_negacao(sessao, operacao)
        raise


def exigir_dono_ou_kernel(super_bloco, processo, operacao):
    """Processo de outro usuário só pode ser tocado pelo root."""
    sessao = _sessao(super_bloco)
    if sessao is None or sessao.usuario.uid in (0, processo.dono_uid):
        return
    exigir_kernel(super_bloco, f"{operacao} (processo '{processo.nome}' pertence a outro usuário)")


# ----------------------------------------------------------------- despacho
def tratar(comando, partes, super_bloco):
    """Executa o comando se for de memória. Devolve True se tratou."""
    if comando in cpu_cmd.COMANDOS or (comando == "create_process" and "--burst" in partes):
        return cpu_cmd.tratar(comando, partes, super_bloco)      # etapa 5
    if comando not in COMANDOS:
        return False

    memoria = super_bloco.memoria
    op = parse_flags(partes[1:])

    if comando == "create_process":
        exigir(op, "name", "size", "type")
        if op["type"] == "critical":
            exigir_kernel(super_bloco, "create_process --type critical")
        sessao = _sessao(super_bloco)
        dono = sessao.usuario.uid if sessao is not None else 0
        proc.criar_processo(super_bloco, op["name"], parse_tamanho(op["size"]), op["type"], dono)

    elif comando == "terminate_process":
        exigir(op, "name")
        processo = proc.obter_processo(super_bloco, op["name"])
        if processo.tipo == "critical":
            exigir_kernel(super_bloco, "terminate_process (processo crítico)")
        else:
            exigir_dono_ou_kernel(super_bloco, processo, "terminate_process")
        proc.encerrar_processo(super_bloco, op["name"])

    elif comando == "memory_status":
        memoria.status(reservada="reserved" in op, virtual="virtual" in op)

    elif comando == "memory_compact":
        exigir_kernel(super_bloco, "memory_compact")
        memoria.compactar()

    elif comando == "translate_address":
        exigir(op, "process", "page")
        processo = proc.obter_processo(super_bloco, op["process"])
        exigir_dono_ou_kernel(super_bloco, processo, "translate_address")
        memoria.traduzir(processo, int(op["page"]))

    elif comando == "execute_step":
        exigir(op, "process", "instruction")
        processo = proc.obter_processo(super_bloco, op["process"])
        exigir_dono_ou_kernel(super_bloco, processo, "execute_step")
        memoria.executar_passo(processo, op["instruction"])

    elif comando == "set_replacement":
        exigir(op, "algo")
        exigir_kernel(super_bloco, "set_replacement")
        memoria.virtual.definir_algoritmo(op["algo"])
        print(f"Algoritmo de substituição definido: {memoria.virtual.algoritmo.nome}")

    memoria.contar_comando()      # só chega aqui se o comando não falhou
    return True
