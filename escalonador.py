"""Motor de CPU: ciclo de vida, syscalls, mutex, Priority + Round-Robin e métricas.

Unidade de escalonamento = processo (thread principal) ou thread extra de um
processo. Todas as unidades de um processo compartilham a tabela de páginas.

Convenções do simulador (1 tick = 1 ms):
  * prioridade menor = mais urgente (1 = Alta); filas por nível, Round-Robin
    dentro do nível e preempção quando chega/volta uma unidade mais urgente;
  * instante de syscall/mutex ("at Xms") = tempo de CPU já consumido pela
    própria unidade (não o relógio global);
  * tempo de espera (WT) = tempo na fila de PRONTO; turnaround = término - chegada;
  * troca de contexto = CPU passa de uma unidade para OUTRA (a 1ª carga não conta).

O motor não imprime nada por conta própria: acumula eventos (`self.eventos`)
com o texto já pronto para o modo passo-a-passo ("step") e para a linha do
tempo ("tl"); quem imprime é comandos_cpu.py.
"""

import io as _io
import random
import re
from collections import deque, OrderedDict
from contextlib import redirect_stdout

NOVO, PRONTO, EXECUTANDO, BLOQUEADO, CONCLUIDO = "NOVO", "PRONTO", "EXECUTANDO", "BLOQUEADO", "CONCLUÍDO"
TRANSICOES = {
    NOVO: {PRONTO},
    PRONTO: {EXECUTANDO},
    EXECUTANDO: {PRONTO, BLOQUEADO, CONCLUIDO},
    BLOQUEADO: {PRONTO},
    CONCLUIDO: set(),
}

QUANTUM_PADRAO = 2
PROB_SYSCALL_ALEATORIA = 0.25     # chance por ms de CPU de disparar o evento aleatório
SYSCALL_BASE_LBA = 3000           # área do RAID usada pelas syscalls de disco
DURACAO_PADRAO_IO = 2
LIMITE_TICKS = 200000


class CPUError(ValueError):
    pass


class Syscall:
    def __init__(self, nome, em, duracao, aleatoria=False):
        self.nome, self.em, self.duracao, self.aleatoria = nome, em, duracao, aleatoria
        self.disparada = False

    @property
    def rotulo(self):
        return {"read_disk": "leitura de disco", "write_disk": "escrita em disco"}.get(self.nome, f"E/S '{self.nome}'")

    @property
    def tipo_bloqueio(self):
        return "E/S de Disco" if self.nome in ("read_disk", "write_disk") else f"E/S ({self.nome})"


class AcaoMutex:
    """lock do mutex quando a unidade atinge `em` ms de CPU; segura por `hold` ms de CPU."""
    def __init__(self, mutex, em, hold):
        self.mutex, self.em, self.hold = mutex, em, hold
        self.estado = "pendente"        # pendente -> aguardando -> segurando -> liberada
        self.liberar_em = None


class Mutex:
    def __init__(self, nome):
        self.nome = nome
        self.dono = None
        self.fila = deque()             # (unidade, acao)


class Unidade:
    def __init__(self, processo, nome, burst, prioridade, chegada, thread=False,
                 paginas=None, seed=0, chegada_cfg=None):
        self.processo = processo
        self.nome = nome
        self.thread = thread
        self.burst = self.restante = burst
        self.prioridade = prioridade
        self.chegada = chegada
        self.chegada_cfg = chegada_cfg
        self.estado = NOVO
        self.historico = []                 # (t, de, para, motivo)
        self.cpu = 0                        # ms de CPU consumidos
        self.espera = 0                     # ms na fila de PRONTO
        self.bloqueado_total = 0
        self.primeira_exec = None
        self.termino = None
        self.syscalls = []
        self.random_io = False
        self.random_feito = False
        self.mutex_acoes = []
        self.motivo_bloq = None             # ("io", syscall) | ("mutex", nome)
        self.desbloqueio_em = None
        self.paginas_cfg = paginas
        self.idx_pag = 0
        self.recentes = []
        self.rng_pag = random.Random(seed)
        self.rng_io = random.Random(seed + 1)
        self.acertos = self.faltas = 0

    @property
    def etiqueta(self):
        return f"PID {self.processo.pid}/{self.nome}" if self.thread else f"PID {self.processo.pid}"

    @property
    def rotulo(self):
        return (f"Thread {self.nome} (PID {self.processo.pid})" if self.thread
                else f"Processo {self.nome} (PID {self.processo.pid})")

    def proxima_pagina(self, n):
        if self.paginas_cfg:
            pagina = self.paginas_cfg[self.idx_pag % len(self.paginas_cfg)]
            self.idx_pag += 1
        elif self.recentes and self.rng_pag.random() < 0.7:
            pagina = self.rng_pag.choice(self.recentes)
        else:
            pagina = self.rng_pag.randrange(n)
        if pagina in self.recentes:
            self.recentes.remove(pagina)
        self.recentes.append(pagina)
        del self.recentes[:-3]
        return pagina


def rotulo_prioridade(p):
    return {1: "Alta", 2: "Baixa"}.get(p, f"Nível {p}")


def estado_processo(processo):
    estados = [u.estado for u in processo.unidades]
    if not estados:
        return None
    if all(e == CONCLUIDO for e in estados):
        return CONCLUIDO
    for e in (EXECUTANDO, PRONTO):
        if e in estados:
            return e
    if all(e in (BLOQUEADO, CONCLUIDO) for e in estados):
        return BLOQUEADO
    return NOVO


class CPU:
    def __init__(self, super_bloco):
        self.sb = super_bloco
        self.quantum = QUANTUM_PADRAO
        self.mutexes = {}
        self.reiniciar_estado()

    def reiniciar_estado(self):
        self.relogio = 0
        self.unidades = []
        self.filas = {}
        self.executando = None
        self.quantum_restante = 0
        self.ultimo = None
        self.trocas = 0
        self.ocupado = 0
        self.ocioso = 0
        self.syscalls_disparadas = 0
        self.bloqueios_mutex = 0
        self.acertos = self.faltas = 0
        self.eventos = []
        self.seg = None
        self.ocioso_ini = None
        self.passo_n = 0
        self._marca = None
        self.ultimo_ms = {}
        self.tocadas = OrderedDict()        # moldura -> (pid, pagina, estado, t)
        self.mutexes = {}

    # ------------------------------------------------------------- eventos
    def _ev(self, tipo, step=(), tl=()):
        """Eventos "tl" que ocorrem DENTRO de um segmento aberto são guardados e impressos
        logo depois da linha do segmento, para a linha do tempo sair em ordem."""
        tl = list(tl)
        if tipo != "seg" and tl and self.seg is not None:
            self.seg["extras"].append({"t": self.relogio, "tipo": tipo, "step": [], "tl": tl})
            tl = []
        self._inserir({"t": self.relogio, "tipo": tipo, "step": list(step), "tl": tl})

    def _inserir(self, ev):
        if ev["tipo"] == "seg" and self._marca is not None:
            self.eventos.insert(self._marca, ev)      # o segmento terminou ANTES dos eventos deste instante
            self._marca += 1
        else:
            self.eventos.append(ev)

    def drenar(self):
        eventos, self.eventos = self.eventos, []
        return eventos

    # --------------------------------------------------------- estados/filas
    def _mudar(self, u, novo, motivo, imprimir=True):
        if novo not in TRANSICOES[u.estado]:
            raise CPUError(f"Transição inválida: {u.estado} -> {novo} ({u.etiqueta})")
        antigo = u.estado
        u.estado = novo
        u.historico.append((self.relogio, antigo, novo, motivo))
        estado_novo = estado_processo(u.processo)
        u.processo.estado = estado_novo
        if imprimir:
            self._ev("estado", step=[f"  - {u.etiqueta}: {antigo} -> {novo} ({motivo})"])

    def _enfileirar(self, u):
        self.filas.setdefault(u.prioridade, deque()).append(u)

    def prontos(self):
        return [u for fila in self.filas.values() for u in fila]

    def _melhor_pronto(self):
        niveis = [p for p, fila in self.filas.items() if fila]
        return self.filas[min(niveis)][0] if niveis else None

    def _admitir(self, u, motivo="chegada ao sistema"):
        self._mudar(u, PRONTO, motivo, imprimir=False)
        self._enfileirar(u)
        self._ev("chegada",
                 step=[f"[t={self.relogio}ms] {u.etiqueta} ({u.nome}): NOVO -> PRONTO (Fila P{u.prioridade})"],
                 tl=[f"[{self.relogio}ms] Chegada: {u.etiqueta} NOVO -> PRONTO (Fila P{u.prioridade})"])

    def adicionar(self, u):
        self.unidades.append(u)
        u.processo.unidades.append(u)
        u.processo.estado = estado_processo(u.processo)
        if u.chegada <= self.relogio:
            self._admitir(u, "criação")

    def remover_processo(self, processo):
        """terminate_process: tira todas as unidades do escalonador."""
        for u in list(processo.unidades):
            for a in u.mutex_acoes:
                if a.estado == "segurando":
                    self._liberar_mutex(u, a, "processo encerrado")
            for m in self.mutexes.values():
                m.fila = deque((w, wa) for w, wa in m.fila if w is not u)
            if self.executando is u:
                self.executando = None
                self.seg = None
            for fila in self.filas.values():
                if u in fila:
                    fila.remove(u)
            if u in self.unidades:
                self.unidades.remove(u)
        processo.unidades = []

    # --------------------------------------------------------------- segmentos
    def _fechar_seg(self, motivo):
        seg, self.seg = self.seg, None
        if seg is None:
            return
        u = seg["u"]
        if seg["ini"] < self.relogio:
            mem = ""
            if seg["hits"] or seg["faltas"]:
                mem = f" [mem: {seg['hits']} HIT, {seg['faltas']} PAGE FAULT]"
            linha = f"[{seg['ini']}ms - {self.relogio}ms] Executando {u.etiqueta} | {motivo}{mem}"
        else:
            linha = f"[{self.relogio}ms] {u.etiqueta} | {motivo}"
        self._inserir({"t": self.relogio, "tipo": "seg", "step": [], "tl": [linha]})
        for extra in seg["extras"]:
            self._inserir({**extra, "tipo": "seg"})

    def fechar_ociosidade(self):
        if self.ocioso_ini is not None and self.ocioso_ini < self.relogio:
            self._inserir({"t": self.relogio, "tipo": "seg", "step": [], "tl": [
                f"[{self.ocioso_ini}ms - {self.relogio}ms] CPU ociosa (todos bloqueados ou aguardando chegada)"]})
        self.ocioso_ini = None

    # ---------------------------------------------------------------- um tick
    def tick(self, forcado=None):
        """Avança 1 ms. Com `forcado`, só ele é despachado (sem preempção/quantum).
        Devolve a unidade que executou, ou None (sem avançar o relógio se `forcado` não pôde rodar)."""
        self._marca = len(self.eventos)
        self._inicio_tick()
        if forcado is not None:
            if self.executando is not None and self.executando is not forcado:
                self._fechar_seg("Interrompido (simulação focada em outro processo) -> Volta p/ Fila de Pronto")
                self._mudar(self.executando, PRONTO, "simulação focada em outro processo")
                self._enfileirar(self.executando)
                self.executando = None
        elif self.executando is not None:
            self._checar_preempcao()

        while self.executando is None:
            u = self._escolher(forcado)
            if u is None:
                break
            self._despachar(u)
            self._gatilhos(u, apos_tick=False)
        self._marca = None

        if self.executando is None:
            if forcado is not None:
                return None
            self._tick_ocioso()
            return None

        u = self.executando
        self._executar(u)
        if self._gatilhos(u, apos_tick=True) and forcado is None and self.quantum_restante <= 0:
            self._fim_quantum(u)
        return u

    def _inicio_tick(self):
        for u in self.unidades:
            if u.estado == NOVO and u.chegada <= self.relogio:
                self._admitir(u)
        for u in self.unidades:
            if u.estado == BLOQUEADO and u.motivo_bloq and u.motivo_bloq[0] == "io" \
                    and u.desbloqueio_em <= self.relogio:
                s = u.motivo_bloq[1]
                u.motivo_bloq = None
                self._mudar(u, PRONTO, "E/S concluída", imprimir=False)
                self._enfileirar(u)
                self._ev("io_fim",
                         step=[f"[t={self.relogio}ms] Evento E/S: {u.etiqueta} encerra {s.rotulo} -> BLOQUEADO -> PRONTO"],
                         tl=[f"[{self.relogio}ms] Evento E/S: {u.etiqueta} encerra {s.rotulo} -> BLOQUEADO -> PRONTO"])

    def _escolher(self, forcado):
        if forcado is not None:
            if forcado.estado != PRONTO:
                return None
            self.filas[forcado.prioridade].remove(forcado)
            return forcado
        melhor = self._melhor_pronto()
        if melhor is None:
            return None
        return self.filas[melhor.prioridade].popleft()

    def _checar_preempcao(self):
        atual = self.executando
        melhor = self._melhor_pronto()
        if melhor is not None and melhor.prioridade < atual.prioridade:
            self._fechar_seg(f"Preemptado por {melhor.etiqueta} (prioridade {melhor.prioridade} > {atual.prioridade}) "
                             f"-> Volta p/ Fila P{atual.prioridade}")
            self._mudar(atual, PRONTO, f"preemptado por {melhor.etiqueta}")
            self._enfileirar(atual)
            self.executando = None

    def _despachar(self, u):
        self.fechar_ociosidade()
        if self.ultimo is not None and self.ultimo is not u:
            self.trocas += 1
            self._ev("troca", step=[f"[t={self.relogio}ms] Troca de contexto #{self.trocas}: {self.ultimo.etiqueta} -> {u.etiqueta}"])
        self.ultimo = u
        self._mudar(u, EXECUTANDO, "despachado pelo escalonador")
        if u.primeira_exec is None:
            u.primeira_exec = self.relogio
        self.executando = u
        self.quantum_restante = self.quantum
        self.seg = {"u": u, "ini": self.relogio, "hits": 0, "faltas": 0, "extras": []}

    def _tick_ocioso(self):
        if self.ocioso_ini is None:
            self.ocioso_ini = self.relogio
        for b in self.unidades:
            if b.estado == BLOQUEADO:
                b.bloqueado_total += 1
        self.relogio += 1
        self.ocioso += 1
        self.passo_n += 1
        self._ev("ocioso", step=[f"--- STEP {self.passo_n} (t={self.relogio}ms) | CPU ociosa (sem unidade PRONTA) ---"])

    def _executar(self, u):
        for w in self.prontos():
            w.espera += 1
        for b in self.unidades:
            if b.estado == BLOQUEADO:
                b.bloqueado_total += 1
        self.relogio += 1
        u.restante -= 1
        u.cpu += 1
        self.ocupado += 1
        self.quantum_restante -= 1
        self.passo_n += 1
        self._ev("passo", step=[f"--- STEP {self.passo_n} (t={self.relogio}ms) | Executando {u.etiqueta} ---"])
        self._referenciar(u)

    def _fim_quantum(self, u):
        if any(p <= u.prioridade and fila for p, fila in self.filas.items()):
            self._fechar_seg(f"Quantum {self.quantum}ms expirou -> Volta p/ Fila P{u.prioridade}")
            self._mudar(u, PRONTO, "quantum expirou")
            self._enfileirar(u)
            self.executando = None
        else:
            self.quantum_restante = self.quantum      # ninguém para revezar: segue executando

    # -------------------------------------------------------- memória (páginas)
    def _referenciar(self, u):
        p = u.processo
        if p.tipo == "critical" or not p.tabela_paginas:
            self._ev("ref", step=[f"CPU executa {u.nome}: acesso direto à Área Reservada (contígua, sem paginação)."])
            return
        mem = self.sb.memoria
        virtual = mem.virtual
        pagina = u.proxima_pagina(len(p.tabela_paginas))
        virtual.relogio = max(virtual.relogio, self.relogio - 1)
        buf = _io.StringIO()
        with redirect_stdout(buf):
            hit, moldura = virtual.acessar(p, pagina, mem.swap)
        saida = buf.getvalue().splitlines()
        algoritmo = virtual.algoritmo.nome
        t = self.relogio
        self.ultimo_ms[(p.pid, pagina)] = t
        if hit:
            u.acertos += 1
            self.acertos += 1
            if self.seg:
                self.seg["hits"] += 1
            if algoritmo == "LRU":
                hist = f"Histórico LRU: Pág {pagina:02d} atualizada (t={t}ms)"
            elif algoritmo == "Segunda Chance":
                hist = f"Bit de referência da Pág {pagina:02d} = 1 (t={t}ms)"
            else:
                hist = f"FIFO: ordem de carga mantida (t={t}ms)"
            linhas = [f"CPU acessa: Página Lógica {pagina:02d} -> [RAM: Moldura {moldura:02d} - HIT] | {hist}"]
            estado = "HIT"
        else:
            u.faltas += 1
            self.faltas += 1
            if self.seg:
                self.seg["faltas"] += 1
            linhas = [f"CPU acessa: Página Lógica {pagina:02d} -> [PAGE FAULT!]"]
            vitima = next((i for i, l in enumerate(saida) if l.startswith("- Removendo Página Lógica")), None)
            if vitima is None:
                linhas.append("RAM com moldura livre: nenhuma substituição necessária.")
            else:
                m = re.search(r"Página Lógica (\d+) do PID (\d+)", saida[vitima])
                vpag, vpid = int(m.group(1)), int(m.group(2))
                if algoritmo == "LRU":
                    ha = t - self.ultimo_ms.get((vpid, vpag), 0)
                    motivo = f"não usada há {ha}ms"
                else:
                    motivo = "mais antiga na RAM" if algoritmo == "FIFO" else "bit de referência 0"
                linhas.append(f"Substituição {algoritmo}: Página Lógica {vpag:02d} do PID {vpid} ({motivo}) removida para o Swap.")
            if any("Trazendo Página Lógica" in l for l in saida):
                linhas.append(f"Página Lógica {pagina:02d} trazida de volta do Swap.")
            trilhas = sum(int(x) for x in re.findall(r"Movimento total: (\d+) trilhas", buf.getvalue()))
            if trilhas:
                linhas.append(f"[E/S] Swap passou pela fila do disco (FCFS) | movimento da cabeça: {trilhas} trilhas")
            linhas.append(f"Página Lógica {pagina:02d} alocada na Moldura {moldura:02d}.")
            estado = "PAGE FAULT (NEW)"
        self.tocadas[moldura] = (p.pid, pagina, estado, t)
        self._ev("ref", step=linhas)

    # ------------------------------------------------------------- gatilhos
    def _gatilhos(self, u, apos_tick):
        """Libera mutex vencidos, conclui, dispara syscalls e tenta mutex. True se segue executando."""
        for a in u.mutex_acoes:
            if a.estado == "segurando" and u.cpu >= a.liberar_em:
                self._liberar_mutex(u, a, f"hold de {a.hold}ms cumprido")
        if u.restante == 0:
            self._concluir(u)
            return False
        for s in u.syscalls:
            if not s.disparada and u.cpu >= s.em:
                self._disparar_syscall(u, s)
                return False
        if apos_tick and u.random_io and not u.random_feito and u.rng_io.random() < PROB_SYSCALL_ALEATORIA:
            u.random_feito = True
            s = Syscall("random_io", u.cpu, u.rng_io.randint(1, 4), aleatoria=True)
            u.syscalls.append(s)
            self._disparar_syscall(u, s)
            return False
        for a in u.mutex_acoes:
            if a.estado == "pendente" and u.cpu >= a.em:
                if not self._tentar_mutex(u, a):
                    return False
        return True

    def _io_disco(self, u, s):
        if s.nome not in ("read_disk", "write_disk"):
            return None
        io = self.sb.gerenciador_io
        lba = SYSCALL_BASE_LBA + (u.processo.pid % 100)
        buf = _io.StringIO()
        with redirect_stdout(buf):
            if s.nome == "write_disk":
                import metodos_arquivos as file
                io.solicitar_escrita(lba, f"io-pid{u.processo.pid}".encode().ljust(file.tamanho_bloco, b"\x00"))
            else:
                io.solicitar_leitura(lba)
            io.processar_fila()
        trilhas = sum(int(x) for x in re.findall(r"Movimento total: (\d+) trilhas", buf.getvalue()))
        op = "ESCRITA" if s.nome == "write_disk" else "LEITURA"
        return f"[E/S] {op} do bloco lógico {lba} enfileirada e atendida no RAID 5 (movimento da cabeça: {trilhas} trilhas)"

    def _disparar_syscall(self, u, s):
        s.disparada = True
        self.syscalls_disparadas += 1
        t = self.relogio
        volta = t + s.duracao
        linha_io = self._io_disco(u, s)
        if s.aleatoria:
            cab = f"[SYSCALL ALEATÓRIA]: {u.etiqueta} disparou um evento de E/S aleatório no instante t={t}ms!"
        else:
            cab = f"[SYSCALL DETECTADA]: {u.etiqueta} atingiu a instrução de {s.rotulo} agendada para t={s.em}ms!"
        step = [cab, f"- Mudança de Estado: EXECUTANDO -> BLOQUEADO ({s.tipo_bloqueio})."]
        if linha_io:
            step.append(f"- {linha_io}")
        step += [f"- Tempo de Retorno Previsto do Bloqueio: {s.duracao}ms (Desbloqueio em t={volta}ms).",
                 "- CPU liberada -> Escalonador seleciona próximo processo da Fila de Pronto."]
        self._ev("syscall", step=step)
        self._fechar_seg(f"Dispara Syscall {s.nome} -> BLOQUEADO (até t={volta}ms)")
        self._mudar(u, BLOQUEADO, s.tipo_bloqueio, imprimir=False)
        u.motivo_bloq = ("io", s)
        u.desbloqueio_em = volta
        self.executando = None

    # ----------------------------------------------------------------- mutex
    def _mutex(self, nome):
        return self.mutexes.setdefault(nome, Mutex(nome))

    def _tentar_mutex(self, u, a):
        m = self._mutex(a.mutex)
        t = self.relogio
        step = [f"[t={t}ms] {u.rotulo} tenta acessar Região Crítica ('{a.mutex}')."]
        if m.dono is None:
            m.dono = u
            a.estado = "segurando"
            a.liberar_em = u.cpu + a.hold
            step.append(f"        Mutex [LIVRE] -> {u.nome} adquire o Mutex [BLOQUEADO].")
            self._ev("mutex", step=step, tl=[f"[{t}ms] {u.etiqueta} ({u.nome}) adquire o Mutex '{a.mutex}'"])
            return True
        a.estado = "aguardando"
        m.fila.append((u, a))
        self.bloqueios_mutex += 1
        step += [f"        Mutex [BLOQUEADO por {m.dono.nome}]!", "",
                 f"        - Mudança de Estado de {u.nome}: EXECUTANDO -> BLOQUEADO (Aguardando Mutex).",
                 "        - CPU liberada -> Escalonador seleciona próximo processo da Fila de Pronto."]
        self._ev("mutex", step=step,
                 tl=[f"[{t}ms] {u.etiqueta} ({u.nome}) tenta o Mutex '{a.mutex}' (dono: {m.dono.nome}) -> BLOQUEADO"])
        self._fechar_seg(f"Aguarda Mutex '{a.mutex}' (de {m.dono.nome}) -> BLOQUEADO")
        self._mudar(u, BLOQUEADO, "Aguardando Mutex", imprimir=False)
        u.motivo_bloq = ("mutex", a.mutex)
        self.executando = None
        return False

    def _liberar_mutex(self, u, a, motivo):
        m = self._mutex(a.mutex)
        a.estado = "liberada"
        m.dono = None
        t = self.relogio
        step = [f"[t={t}ms] {u.rotulo} libera o Mutex '{a.mutex}' ({motivo}) -> [LIVRE]"]
        tl = [f"[{t}ms] {u.etiqueta} ({u.nome}) libera o Mutex '{a.mutex}'"]
        if m.fila:
            w, wa = m.fila.popleft()
            m.dono = w
            wa.estado = "segurando"
            wa.liberar_em = w.cpu + wa.hold
            w.motivo_bloq = None
            self._mudar(w, PRONTO, "Mutex liberado", imprimir=False)
            self._enfileirar(w)
            step += [f"        {w.rotulo} acorda: BLOQUEADO -> PRONTO e adquire o Mutex [BLOQUEADO].",]
            tl.append(f"[{t}ms] {w.etiqueta} ({w.nome}) BLOQUEADO -> PRONTO e adquire o Mutex '{a.mutex}'")
        self._ev("mutex", step=step, tl=tl)

    # -------------------------------------------------------------- conclusão
    def _concluir(self, u):
        for a in u.mutex_acoes:
            if a.estado == "segurando":
                self._liberar_mutex(u, a, "unidade concluída")
        self._fechar_seg(f"{u.etiqueta} CONCLUÍDO!")
        self._mudar(u, CONCLUIDO, "burst finalizado")
        u.termino = self.relogio
        self.executando = None
        p = u.processo
        if all(x.estado == CONCLUIDO for x in p.unidades):
            self._liberar_memoria(p)

    def _liberar_memoria(self, p):
        if getattr(p, "memoria_liberada", False):
            return
        with redirect_stdout(_io.StringIO()):
            self.sb.memoria.liberar(p)
        for e in (p.tabela_paginas or []):
            e.presente, e.moldura, e.slot_swap = False, None, None
        p.memoria_liberada = True
        self._ev("mem", step=[f"[t={self.relogio}ms] {p.nome} (PID {p.pid}) CONCLUÍDO: memória liberada ao SO."])

    # --------------------------------------------------------------- consultas
    def escalonaveis(self):
        return [u for u in self.unidades if u.estado != CONCLUIDO]

    def deadlock(self):
        ativos = self.escalonaveis()
        if not ativos or self.executando is not None or self.prontos():
            return False
        if any(u.estado == NOVO for u in ativos):
            return False
        if any(u.estado == BLOQUEADO and u.motivo_bloq and u.motivo_bloq[0] == "io" for u in ativos):
            return False
        return any(u.estado == BLOQUEADO for u in ativos)

    def reset(self):
        """sim_reset: volta todas as unidades ao início (mantém processos e memória)."""
        unidades = list(self.unidades)
        self.reiniciar_estado()
        for u in unidades:
            u.restante, u.cpu, u.espera, u.bloqueado_total = u.burst, 0, 0, 0
            u.primeira_exec = u.termino = u.desbloqueio_em = u.motivo_bloq = None
            u.estado, u.historico = NOVO, []
            u.random_feito = False
            u.acertos = u.faltas = u.idx_pag = 0
            u.recentes = []
            for s in u.syscalls:
                s.disparada = False
            u.syscalls = [s for s in u.syscalls if not s.aleatoria]
            for a in u.mutex_acoes:
                a.estado, a.liberar_em = "pendente", None
            u.chegada = u.chegada_cfg or 0
            self.unidades.append(u)
            u.processo.memoria_liberada = False
        for u in self.unidades:
            if u.chegada <= 0:
                self._admitir(u, "reinício da simulação")
            u.processo.estado = estado_processo(u.processo)
        self.drenar()

    def metricas(self):
        linhas = []
        for u in self.unidades:
            concluida = u.termino is not None
            tat = u.termino - u.chegada if concluida else None
            resposta = u.primeira_exec - u.chegada if u.primeira_exec is not None else None
            linhas.append({"u": u, "wt": u.espera, "tat": tat, "resposta": resposta,
                           "bloqueado": u.bloqueado_total})
        return linhas
