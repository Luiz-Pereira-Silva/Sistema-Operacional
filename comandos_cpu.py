"""Comandos da etapa de Processos/CPU (etapa 5).

Ligado ao resto só por comandos_memoria.py (despacho) e por `iniciar_cpu`
(chamado em iniciar_memoria). Segurança por duck typing, como na memória:
sem `sessao` tudo roda como root.

  create_process --name N --burst 8ms --priority 1 [--type normal|critical]
                 [--size 32KB] [--arrival 0ms] [--pages 2,7,4] [--seed N]
                 [--syscall "read_disk at 3ms (duration: 4ms)"]... [--syscall random]
                 [--mutex "Buffer at 1ms hold 3ms"]...
  thread_create --process N --name T1 --burst 3ms [mesmas opções de syscall/mutex]
  run_simulation [--process N [--thread T1]] --steps K
  schedule --algorithm Priority_RR --quantum 2ms
  ps [--history] | metrics | mutex_status | sim_reset
"""

import io as _io
import re
from contextlib import redirect_stdout

import comandos_memoria as cm
import processo as proc
from escalonador import (CPU, Unidade, Syscall, AcaoMutex, rotulo_prioridade, estado_processo,
                         NOVO, PRONTO, EXECUTANDO, BLOQUEADO, CONCLUIDO,
                         DURACAO_PADRAO_IO, LIMITE_TICKS)
from memoria import parse_tamanho, fragmentacao_interna, TAM_PAGINA

COMANDOS = {"run_simulation", "schedule", "thread_create", "ps", "metrics", "mutex_status", "sim_reset"}
TAMANHO_PADRAO_NORMAL = 8 * TAM_PAGINA          # 32 KB (8 páginas)
TAMANHO_PADRAO_CRITICO = 256 * 1024

SYSCALL_RE = re.compile(r"^(?P<nome>\w+)\s+at\s+(?P<em>\d+)\s*ms"
                        r"(?:\s*\(?\s*duration\s*:?\s*(?P<dur>\d+)\s*ms\s*\)?)?$", re.IGNORECASE)
MUTEX_RE = re.compile(r"^(?P<nome>\w+)\s+at\s+(?P<em>\d+)\s*ms(?:\s+hold\s+(?P<hold>\d+)\s*ms)?$", re.IGNORECASE)


def iniciar_cpu(super_bloco):
    super_bloco.cpu = CPU(super_bloco)


# ----------------------------------------------------------------- argumentos
def parse_multi(argumentos):
    """['--syscall','a','--syscall','b','--x'] -> {'syscall': ['a','b'], 'x': [True]}"""
    opcoes = {}
    i = 0
    while i < len(argumentos):
        if not argumentos[i].startswith("--"):
            raise ValueError(f"Argumento inesperado: {argumentos[i]}")
        chave = argumentos[i][2:]
        if i + 1 < len(argumentos) and not argumentos[i + 1].startswith("--"):
            opcoes.setdefault(chave, []).append(argumentos[i + 1])
            i += 2
        else:
            opcoes.setdefault(chave, []).append(True)
            i += 1
    return opcoes


def um(op, chave, padrao=None):
    valor = op.get(chave, [padrao])[-1]
    if valor is True:
        raise ValueError(f"A opção --{chave} precisa de um valor")
    return valor


def parse_ms(texto, nome, minimo=0):
    m = re.fullmatch(r"(\d+)\s*(?:ms)?", str(texto).strip().lower())
    if not m or int(m.group(1)) < minimo:
        raise ValueError(f"{nome} inválido: use um inteiro em ms >= {minimo} (ex.: 8ms)")
    return int(m.group(1))


def parse_inteiro(texto, nome, minimo=1):
    try:
        valor = int(texto)
    except (TypeError, ValueError):
        raise ValueError(f"{nome} inválido: use um inteiro >= {minimo}")
    if valor < minimo:
        raise ValueError(f"{nome} inválido: use um inteiro >= {minimo}")
    return valor


def parse_syscalls(textos, burst):
    syscalls, aleatoria = [], False
    for texto in textos:
        if texto is True:
            raise ValueError('--syscall precisa de um valor (ex.: "read_disk at 3ms (duration: 4ms)" ou random)')
        if texto.strip().lower() == "random":
            aleatoria = True
            continue
        m = SYSCALL_RE.match(texto.strip())
        if not m:
            raise ValueError(f'Syscall inválida: "{texto}" (use "nome at Xms (duration: Yms)" ou random)')
        em = int(m.group("em"))
        dur = int(m.group("dur")) if m.group("dur") else DURACAO_PADRAO_IO
        if dur < 1:
            raise ValueError("A duração do bloqueio deve ser de pelo menos 1ms")
        if em >= burst:
            raise ValueError(f"A syscall '{m.group('nome')}' em t={em}ms cai fora do burst ({burst}ms): use t < burst")
        syscalls.append(Syscall(m.group("nome").lower(), em, dur))
    return syscalls, aleatoria


def parse_mutexes(textos, burst):
    acoes = []
    for texto in textos:
        if texto is True:
            raise ValueError('--mutex precisa de um valor (ex.: "Buffer_Video at 1ms hold 3ms")')
        m = MUTEX_RE.match(texto.strip())
        if not m:
            raise ValueError(f'Mutex inválido: "{texto}" (use "nome at Xms hold Yms")')
        em = int(m.group("em"))
        hold = int(m.group("hold")) if m.group("hold") else 2
        if hold < 1:
            raise ValueError("O hold do mutex deve ser de pelo menos 1ms")
        if em >= burst:
            raise ValueError(f"O mutex '{m.group('nome')}' em t={em}ms cai fora do burst ({burst}ms): use t < burst")
        acoes.append(AcaoMutex(m.group("nome"), em, hold))
    return acoes


def parse_paginas(texto, n_paginas):
    if texto is None:
        return None
    try:
        paginas = [int(x) for x in str(texto).split(",") if x.strip() != ""]
    except ValueError:
        raise ValueError("--pages inválido: use uma lista de páginas separadas por vírgula (ex.: 2,7,4)")
    if not paginas:
        raise ValueError("--pages vazio")
    for pagina in paginas:
        if not 0 <= pagina < n_paginas:
            raise ValueError(f"--pages: página {pagina} fora do processo (0 a {n_paginas - 1})")
    return paginas


# ------------------------------------------------------------------- criação
def _preencher_unidade(cpu, u, op, burst):
    syscalls, aleatoria = parse_syscalls(op.get("syscall", []), burst)
    u.syscalls = syscalls
    u.random_io = aleatoria
    u.mutex_acoes = parse_mutexes(op.get("mutex", []), burst)


def _descrever_unidade(u):
    for s in u.syscalls:
        print(f"Syscall/I/O  : Agendada para t={s.em}ms (Duração do Bloqueio: {s.duracao}ms) [{s.nome}]")
    if u.random_io:
        print("Syscall/I/O  : Evento Aleatório Habilitado")
    for a in u.mutex_acoes:
        print(f"Mutex        : '{a.mutex}' em t={a.em}ms (segura por {a.hold}ms de CPU)")


def _estado_inicial(cpu, u):
    if u.estado == NOVO:
        return f"NOVO (chega em t={u.chegada}ms)"
    return "PRONTO"


def criar_processo_cpu(sb, partes):
    op = parse_multi(partes[1:])
    for chave in ("name", "burst"):
        if chave not in op:
            raise ValueError(f"Parâmetro obrigatório ausente: --{chave}")
    nome = um(op, "name")
    burst = parse_ms(um(op, "burst"), "Burst", minimo=1)
    prioridade = parse_inteiro(um(op, "priority", "1"), "Prioridade", 1)
    tipo = um(op, "type", "normal")
    tamanho = (parse_tamanho(um(op, "size")) if "size" in op
               else TAMANHO_PADRAO_CRITICO if tipo == "critical" else TAMANHO_PADRAO_NORMAL)
    cpu = sb.cpu
    chegada = parse_ms(um(op, "arrival"), "Chegada") if "arrival" in op else None
    seed_cfg = parse_inteiro(um(op, "seed"), "Seed", 0) if "seed" in op else None

    if tipo == "critical":
        cm.exigir_kernel(sb, "create_process --type critical")
    sessao = cm._sessao(sb)
    dono = sessao.usuario.uid if sessao is not None else 0

    # valida o que dá para validar antes de alocar memória
    syscalls_ok = parse_syscalls(op.get("syscall", []), burst)
    mutexes_ok = parse_mutexes(op.get("mutex", []), burst)

    n_paginas = fragmentacao_interna(tamanho)[0]
    paginas = parse_paginas(um(op, "pages"), n_paginas) if tipo == "normal" else None

    buf = _io.StringIO()
    with redirect_stdout(buf):
        p = proc.criar_processo(sb, nome, tamanho, tipo, dono)
    saida = buf.getvalue()

    p.prioridade, p.burst = prioridade, burst
    seed = seed_cfg if seed_cfg is not None else (p.pid * 7919) & 0xFFFF
    u = Unidade(p, nome, burst, prioridade, cpu.relogio if chegada is None else chegada,
                paginas=paginas, seed=seed, chegada_cfg=chegada)
    u.syscalls, u.random_io = syscalls_ok
    u.mutex_acoes = mutexes_ok
    cpu.adicionar(u)
    cpu.drenar()

    print(f"[CRIAÇÃO DE PROCESSO] PID: {p.pid} | Nome: {nome} | Prioridade: {prioridade} ({rotulo_prioridade(prioridade)})")
    if tipo == "critical":
        linha = next((l for l in saida.splitlines() if "Área Reservada" in l), "").lstrip("- ").strip()
        print(f"Alocação     : Área Reservada Contígua (sem paginação) | {linha.split(': ', 1)[-1]}")
    else:
        n = len(p.tabela_paginas)
        print(f"Alocação     : Memória Virtual Paginada (Tabela de Páginas criada) | {n} página(s) de {TAM_PAGINA // 1024} KB")
    print(f"Burst Time   : {burst}ms | Tipo: {tipo}")
    _descrever_unidade(u)
    print(f"Estado Inicial: {_estado_inicial(cpu, u)}")
    cm_mem = sb.memoria
    cm_mem.contar_comando()


def criar_thread(sb, partes):
    op = parse_multi(partes[1:])
    for chave in ("process", "name", "burst"):
        if chave not in op:
            raise ValueError(f"Parâmetro obrigatório ausente: --{chave}")
    p = proc.obter_processo(sb, um(op, "process"))
    cm.exigir_dono_ou_kernel(sb, p, "thread_create")
    if not p.unidades:
        raise ValueError(f"O processo '{p.nome}' não tem perfil de CPU (crie com --burst)")
    if estado_processo(p) == CONCLUIDO:
        raise ValueError(f"O processo '{p.nome}' já foi concluído")
    nome = um(op, "name")
    if nome == p.nome or any(u.nome == nome for u in p.unidades):
        raise ValueError(f"Já existe uma thread/unidade chamada '{nome}' no processo '{p.nome}'")
    burst = parse_ms(um(op, "burst"), "Burst", minimo=1)
    prioridade = parse_inteiro(um(op, "priority"), "Prioridade", 1) if "priority" in op else p.prioridade
    cpu = sb.cpu
    chegada = parse_ms(um(op, "arrival"), "Chegada") if "arrival" in op else None
    paginas = parse_paginas(um(op, "pages"), len(p.tabela_paginas)) if p.tabela_paginas else None
    seed = parse_inteiro(um(op, "seed"), "Seed", 0) if "seed" in op else (p.pid * 7919 + len(p.unidades) * 31) & 0xFFFF
    u = Unidade(p, nome, burst, prioridade, cpu.relogio if chegada is None else chegada,
                thread=True, paginas=paginas, seed=seed, chegada_cfg=chegada)
    _preencher_unidade(cpu, u, op, burst)
    cpu.adicionar(u)
    cpu.drenar()
    print(f"[CRIAÇÃO DE THREAD] Thread {nome} em PID {p.pid} ({p.nome}) | Prioridade: {prioridade} ({rotulo_prioridade(prioridade)})")
    print(f"Burst Time   : {burst}ms | Compartilha a Tabela de Páginas do processo")
    _descrever_unidade(u)
    print(f"Estado Inicial: {_estado_inicial(cpu, u)}")


# ----------------------------------------------------------------- impressão
def imprimir_eventos(cpu, modo):
    chave = "step" if modo == "passo" else "tl"
    for ev in cpu.drenar():
        for linha in ev[chave]:
            print(linha)


def imprimir_resumo_ram(sb, cpu):
    virtual = sb.memoria.virtual
    linhas = []
    for moldura, (pid, pagina, estado, t) in cpu.tocadas.items():
        if virtual.molduras[moldura] == (pid, pagina):
            linhas.append((moldura, pid, pagina, estado, t))
    print("\n[RESUMO DA GERÊNCIA DE MEMÓRIA (RAM DINÂMICA)]")
    borda = "+------------------+---------------+-------------------+---------------------+"
    print(borda)
    print("| Moldura RAM (F)  | Processo/Pág  | Estado de Acesso  | Último Acesso (LRU) |")
    print(borda)
    if not linhas:
        print("| (nenhuma moldura da RAM dinâmica foi referenciada neste intervalo)               |")
    for moldura, pid, pagina, estado, t in sorted(linhas, key=lambda x: x[4]):
        rot_f, rot_p, rot_t = f"Moldura {moldura:02d}", f"PID {pid} / P{pagina}", f"t = {t} ms"
        print(f"| {rot_f:^16} | {rot_p:^13} | {estado:<17} | {rot_t:<19} |")
    print(borda)
    total = len(virtual.molduras)
    print(f"Molduras em uso: {virtual.usadas()}/{total} | Algoritmo: {virtual.algoritmo.nome}")


def imprimir_metricas(cpu):
    linhas = cpu.metricas()
    if not linhas:
        print("Nenhum processo com perfil de CPU (crie com create_process --burst ...).")
        return
    borda = "+------------+------------+---------------+-------+-------------------+---------------------+----------+------------+"
    print("\n================ METRICAS FINAIS DO ESCALONADOR ================")
    print(borda)
    print("| Processo   | Prioridade | Tempo Chegada | Burst | Tempo Espera (WT) | Turnaround Time(TAT)| Resposta | Bloqueado  |")
    print(borda)
    for m in linhas:
        u = m["u"]
        tat = f"{m['tat']} ms" if m["tat"] is not None else "-"
        resp = f"{m['resposta']} ms" if m["resposta"] is not None else "-"
        chegada, burst = f"{u.chegada} ms", f"{u.burst}ms"
        wt, bloq = f"{m['wt']} ms", f"{m['bloqueado']} ms"
        print(f"| {u.etiqueta:<10} | {u.prioridade:^10} | {chegada:^13} | {burst:^5} | "
              f"{wt:^17} | {tat:^19} | {resp:^8} | {bloq:^10} |")
    print(borda)
    concluidas = [m for m in linhas if m["tat"] is not None]
    if concluidas:
        n = len(concluidas)
        print(f"\n* Tempo Médio de Espera (AWT)   : {sum(m['wt'] for m in concluidas) / n:.2f} ms")
        print(f"* Tempo Médio de Retorno (ATT)  : {sum(m['tat'] for m in concluidas) / n:.2f} ms")
        print(f"* Tempo Médio de Resposta (ART) : {sum(m['resposta'] for m in concluidas) / n:.2f} ms")
    if len(concluidas) < len(linhas):
        print(f"* Unidades ainda não concluídas: {len(linhas) - len(concluidas)} (médias só das concluídas)")
    print(f"* Trocas de Contexto Totais     : {cpu.trocas} trocas")
    if cpu.relogio:
        print(f"* Utilização Global da CPU      : {100 * cpu.ocupado / cpu.relogio:.0f}% "
              f"({cpu.ocupado}ms ocupada / {cpu.ocioso}ms ociosa)")
        print(f"* Vazão (throughput)            : {len(concluidas) / cpu.relogio:.3f} unidade(s)/ms")
    acessos = cpu.acertos + cpu.faltas
    taxa = f"{100 * cpu.acertos / acessos:.1f}%" if acessos else "n/a"
    print(f"* Referências a páginas         : {acessos} | HIT: {cpu.acertos} | PAGE FAULT: {cpu.faltas} | Taxa de acerto: {taxa}")
    print(f"* Syscalls disparadas           : {cpu.syscalls_disparadas}")
    print(f"* Bloqueios por Mutex           : {cpu.bloqueios_mutex}")


def imprimir_ps(cpu, historico):
    if not cpu.unidades:
        print("Nenhum processo com perfil de CPU.")
        return
    print(f"[ESTADO DOS PROCESSOS] t={cpu.relogio}ms | Quantum: {cpu.quantum}ms")
    print(f"{'Unidade':<12}{'Nome':<18}{'Tipo':<9}{'Prio':<6}{'Estado':<13}{'Restante':<10}{'Bloqueio'}")
    for u in cpu.unidades:
        bloq = ""
        if u.estado == BLOQUEADO and u.motivo_bloq:
            bloq = (f"E/S até t={u.desbloqueio_em}ms" if u.motivo_bloq[0] == "io"
                    else f"Mutex '{u.motivo_bloq[1]}'")
        print(f"{u.etiqueta:<12}{u.nome:<18}{u.processo.tipo:<9}{u.prioridade:<6}{u.estado:<13}"
              f"{f'{u.restante}/{u.burst}ms':<10}{bloq}")
    if historico:
        for u in cpu.unidades:
            print(f"\nCiclo de vida de {u.etiqueta} ({u.nome}):")
            for t, de, para, motivo in u.historico:
                print(f"  t={t}ms: {de} -> {para} ({motivo})")


def imprimir_mutexes(cpu):
    if not cpu.mutexes:
        print("Nenhum mutex em uso.")
        return
    for m in cpu.mutexes.values():
        dono = f"BLOQUEADO por {m.dono.nome} ({m.dono.etiqueta})" if m.dono else "LIVRE"
        fila = ", ".join(u.nome for u, _ in m.fila) or "vazia"
        print(f"Mutex '{m.nome}': [{dono}] | Fila de espera: {fila}")


def imprimir_fila_inicial(cpu):
    print("Fila de Pronto Inicial:")
    niveis = sorted({u.prioridade for u in cpu.escalonaveis()})
    for p in niveis:
        itens = []
        for u in cpu.escalonaveis():
            if u.prioridade != p:
                continue
            nota = f", chega em {u.chegada}ms" if u.estado == NOVO else ""
            itens.append(f"{u.etiqueta} (Burst {u.restante}ms{nota})")
        print(f"- Prioridade {p} ({rotulo_prioridade(p)}) : [{', '.join(itens)}]")


# ------------------------------------------------------------------ comandos
def _unidade_alvo(sb, op):
    p = proc.obter_processo(sb, um(op, "process"))
    if not p.unidades:
        raise ValueError(f"O processo '{p.nome}' não tem perfil de CPU (crie com --burst)")
    nome = um(op, "thread", None)
    if nome is None:
        return p, p.unidades[0]
    u = next((x for x in p.unidades if x.nome == nome and x.thread), None)
    if u is None:
        raise ValueError(f"Thread '{nome}' inexistente no processo '{p.nome}'")
    return p, u


def comando_run_simulation(sb, op):
    cpu = sb.cpu
    passos = parse_inteiro(um(op, "steps", "1"), "--steps", 1)
    alvo = None
    if "process" in op:
        p, alvo = _unidade_alvo(sb, op)
        cm.exigir_dono_ou_kernel(sb, p, "run_simulation")
    else:
        cm.exigir_kernel(sb, "run_simulation (sem --process)")
        if not cpu.escalonaveis():
            raise ValueError("Nenhum processo escalonável (use create_process --burst ...)")
    if alvo is not None and alvo.estado not in (PRONTO, EXECUTANDO):
        detalhe = f" (chega em t={alvo.chegada}ms)" if alvo.estado == NOVO else ""
        raise ValueError(f"{alvo.etiqueta} não pode executar: estado {alvo.estado}{detalhe}")
    cpu.tocadas.clear()
    cpu.passo_n = 0
    cpu.drenar()
    executados = 0
    for _ in range(passos):
        cpu.tick(alvo)
        imprimir_eventos(cpu, "passo")
        executados += 1
        if alvo is not None and alvo.estado not in (PRONTO, EXECUTANDO):
            break
    if alvo is not None and executados < passos:
        print(f"\n[SIMULAÇÃO] {alvo.etiqueta} parou após {executados} passo(s): estado {alvo.estado}.")
    imprimir_resumo_ram(sb, cpu)


def comando_schedule(sb, op):
    cpu = sb.cpu
    cm.exigir_kernel(sb, "schedule")
    algoritmo = um(op, "algorithm", "Priority_RR")
    if algoritmo.lower() != "priority_rr":
        raise ValueError("Algoritmo inválido (use Priority_RR)")
    quantum = parse_ms(um(op, "quantum", str(cpu.quantum)), "Quantum", minimo=1)
    if not cpu.escalonaveis():
        raise ValueError("Nenhum processo escalonável (use create_process --burst ...)")
    cpu.quantum = quantum
    cpu.quantum_restante = min(cpu.quantum_restante, quantum) if cpu.executando else cpu.quantum_restante
    print(f"[ESCALONADOR] Algoritmo: Priority_RR | Quantum: {quantum}ms | t inicial = {cpu.relogio}ms")
    imprimir_fila_inicial(cpu)
    print("\n--- LINHA DO TEMPO DA CPU ---")
    cpu.drenar()
    ticks = 0
    while cpu.escalonaveis():
        if cpu.deadlock():
            cpu.fechar_ociosidade()
            imprimir_eventos(cpu, "tl")
            print(f"[{cpu.relogio}ms] [DEADLOCK] Nenhuma unidade pode prosseguir: "
                  + "; ".join(f"{u.etiqueta} aguarda Mutex '{u.motivo_bloq[1]}'" for u in cpu.escalonaveis()
                              if u.motivo_bloq))
            break
        if ticks >= LIMITE_TICKS:
            print("[ERRO] Limite de ticks da simulação atingido.")
            break
        cpu.tick()
        ticks += 1
        imprimir_eventos(cpu, "tl")
    cpu.fechar_ociosidade()
    imprimir_eventos(cpu, "tl")
    imprimir_metricas(cpu)


# ------------------------------------------------------------------- despacho
def tratar(comando, partes, sb):
    cpu = sb.cpu
    if comando == "create_process":
        criar_processo_cpu(sb, partes)
    elif comando == "thread_create":
        criar_thread(sb, partes)
    elif comando == "run_simulation":
        comando_run_simulation(sb, parse_multi(partes[1:]))
    elif comando == "schedule":
        comando_schedule(sb, parse_multi(partes[1:]))
    elif comando == "ps":
        imprimir_ps(cpu, "history" in parse_multi(partes[1:]))
    elif comando == "metrics":
        imprimir_metricas(cpu)
    elif comando == "mutex_status":
        imprimir_mutexes(cpu)
    elif comando == "sim_reset":
        cm.exigir_kernel(sb, "sim_reset")
        cpu.reset()
        print("[SIMULAÇÃO] Relógio, estados, filas, mutexes e métricas reiniciados "
              f"({len(cpu.unidades)} unidade(s) de volta ao início). Memória mantida.")
    return True
