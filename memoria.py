"""Gerenciamento de Memória: modelo híbrido.

RAM simulada = Região Reservada (contígua, sem paginação: kernel e processos
críticos) + Região Dinâmica (memória virtual paginada, processos normais).
O swap (swap.py) é gravado no RAID 5 pelo GerenciadorIO (passa pelo escalonador FCFS).
"""

import math
import re

from swap import Swap

TAM_PAGINA = 4096                    # 4 KB
RAM_RESERVADA = 4 * 1024 * 1024      # 4 MB
TAM_NUCLEO = 1 * 1024 * 1024         # Núcleo Base do SO (fixo)
NUM_MOLDURAS = 128                   # molduras da região dinâmica (512 KB)
INTERVALO_RELATORIO = 5              # relatório periódico a cada N comandos de memória


class MemoriaError(ValueError):
    pass


# ----------------------------------------------------------------- utilitários
def parse_tamanho(texto):
    m = re.fullmatch(r"(\d+)\s*(B|KB|MB)", str(texto).strip().upper())
    if not m:
        raise MemoriaError("Tamanho inválido (use B, KB ou MB, ex.: 512KB)")
    valor = int(m.group(1)) * {"B": 1, "KB": 1024, "MB": 1024 * 1024}[m.group(2)]
    if valor <= 0:
        raise MemoriaError("O tamanho deve ser maior que zero")
    return valor


def fmt_mb(b):
    return f"{b / (1024 * 1024):.1f} MB"


def fmt_kb(b):
    return f"{b // 1024} KB" if b % 1024 == 0 else f"{b / 1024:.1f} KB"


def fragmentacao_interna(tamanho):
    """Devolve (n_paginas, bytes_desperdicados)."""
    n = math.ceil(tamanho / TAM_PAGINA)
    return n, n * TAM_PAGINA - tamanho


# ------------------------------------------------------------ região reservada
class Bloco:
    def __init__(self, inicio, tamanho, pid=None, nome=None):
        self.inicio = inicio
        self.tamanho = tamanho
        self.pid = pid
        self.nome = nome

    @property
    def fim(self):
        return self.inicio + self.tamanho

    @property
    def livre(self):
        return self.pid is None


class AreaReservada:
    """Alocação contígua (first-fit) com fragmentação externa e compactação."""

    def __init__(self, total=RAM_RESERVADA, nucleo=TAM_NUCLEO):
        self.total = total
        self.blocos = [Bloco(0, nucleo, 0, "Núcleo Base do SO"), Bloco(nucleo, total - nucleo)]

    def alocar(self, processo):
        for i, bloco in enumerate(self.blocos):
            if bloco.livre and bloco.tamanho >= processo.tamanho:
                novo = Bloco(bloco.inicio, processo.tamanho, processo.pid, processo.nome)
                resto = bloco.tamanho - processo.tamanho
                self.blocos[i] = novo
                if resto:
                    self.blocos.insert(i + 1, Bloco(novo.fim, resto))
                processo.base = novo.inicio
                return novo
        d = self.diagnostico()
        if d["livre_total"] >= processo.tamanho:
            raise MemoriaError(
                f"Fragmentação externa: há {fmt_kb(d['livre_total'])} livres, mas o maior bloco "
                f"contíguo é {fmt_kb(d['maior_bloco'])}. Execute 'memory_compact --reserved'."
            )
        raise MemoriaError(
            f"Memória reservada insuficiente: pedido {fmt_kb(processo.tamanho)}, "
            f"livre {fmt_kb(d['livre_total'])}."
        )

    def liberar(self, pid):
        for bloco in self.blocos:
            if bloco.pid == pid and pid != 0:
                intervalo = (bloco.inicio, bloco.fim, bloco.tamanho)
                bloco.pid = None
                bloco.nome = None
                self._fundir()
                return intervalo
        raise MemoriaError("Processo não possui bloco na área reservada")

    def _fundir(self):
        fundidos = []
        for bloco in self.blocos:
            if fundidos and fundidos[-1].livre and bloco.livre:
                fundidos[-1].tamanho += bloco.tamanho
            else:
                fundidos.append(bloco)
        self.blocos = fundidos

    def diagnostico(self):
        lacunas = [b for b in self.blocos if b.livre]
        livre = sum(b.tamanho for b in lacunas)
        return {
            "lacunas": len(lacunas),
            "livre_total": livre,
            "ocupado": self.total - livre,
            "maior_bloco": max((b.tamanho for b in lacunas), default=0),
            "externa": len(lacunas) > 1,
        }

    def compactar(self, processos):
        """Desliza os blocos ocupados para o início. Devolve os blocos movidos."""
        movidos, novos, cursor = [], [], 0
        for bloco in self.blocos:
            if bloco.livre:
                continue
            if bloco.inicio != cursor:
                movidos.append((bloco.nome, bloco.inicio, bloco.fim, cursor, cursor + bloco.tamanho))
                bloco.inicio = cursor
                if bloco.pid in processos:
                    processos[bloco.pid].base = cursor
            novos.append(bloco)
            cursor = bloco.fim
        if cursor < self.total:
            novos.append(Bloco(cursor, self.total - cursor))
        self.blocos = novos
        return movidos

    def imprimir_mapa(self):
        print(f"--- MAPA DA ÁREA CRÍTICA/RESERVADA DA RAM (Total: {self.total // (1024 * 1024)} MB - Alocação Fixa) ---")
        n_lacunas = sum(1 for b in self.blocos if b.livre)
        numero = 0
        for b in self.blocos:
            if b.livre:
                numero += 1
                nome = "Bloco Livre Contíguo" if n_lacunas == 1 else f"FRAGMENTO LIVRE {numero}"
                estado = "[LIVRE]" if n_lacunas == 1 else "[LIVRE - LACUNA]"
            else:
                nome, estado = b.nome, "[OCUPADO]"
            print(f"[{fmt_mb(b.inicio)} - {fmt_mb(b.fim)}] : {nome.ljust(20)} ({fmt_kb(b.tamanho)}) {estado}")

    def imprimir_diagnostico(self):
        d = self.diagnostico()
        pct = 100 * d["ocupado"] / self.total
        print("\n--- DIAGNÓSTICO DE FRAGMENTAÇÃO EXTERNA ---")
        print(f"Total de Memória Livre na Área Reservada : {fmt_kb(d['livre_total'])} ({fmt_mb(d['livre_total'])})")
        print(f"Maior Bloco Contíguo Disponível          : {fmt_kb(d['maior_bloco'])} ({fmt_mb(d['maior_bloco'])})")
        if d["externa"]:
            print(f"Fragmentação Externa Detectada           : SIM ({d['lacunas']} fragmentos não contíguos)")
            print(f"Status: Uma requisição contígua maior que {fmt_kb(d['maior_bloco'])} falhará por ausência de bloco único.")
        else:
            print("Fragmentação Externa Detectada           : NÃO")
        print(f"Ocupação da Área Reservada               : {fmt_kb(d['ocupado'])} de {fmt_kb(self.total)} ({pct:.1f}%)")


# ------------------------------------------------------- algoritmos de troca
class Pagina:
    def __init__(self):
        self.presente = False
        self.moldura = None
        self.bit_ref = 0
        self.ultimo_acesso = 0
        self.slot_swap = None


class LRU:
    nome = "LRU"

    @staticmethod
    def escolher_vitima(mem):
        melhor = None
        for i, ocupante in enumerate(mem.molduras):
            if ocupante is None:
                continue
            pid, pag = ocupante
            ultimo = mem.entrada(pid, pag).ultimo_acesso
            if melhor is None or ultimo < melhor[0]:
                melhor = (ultimo, i, pid, pag)
        ultimo, moldura, pid, pag = melhor
        return moldura, (f"Analisando histórico de acesso: Página Lógica {pag} do PID {pid} "
                         f"não é usada há {mem.relogio - ultimo} ticks (Mais antiga).")


class FIFO:
    nome = "FIFO"

    @staticmethod
    def escolher_vitima(mem):
        moldura = mem.ordem_carga[0]
        pid, pag = mem.molduras[moldura]
        return moldura, f"Página Lógica {pag} do PID {pid} é a que está há mais tempo na RAM (FIFO)."


class SegundaChance:
    nome = "Segunda Chance"

    @staticmethod
    def escolher_vitima(mem):
        chances = 0
        while True:
            moldura = mem.ordem_carga[0]
            pid, pag = mem.molduras[moldura]
            entrada = mem.entrada(pid, pag)
            if entrada.bit_ref:
                entrada.bit_ref = 0
                mem.ordem_carga.append(mem.ordem_carga.pop(0))
                chances += 1
            else:
                return moldura, (f"Página Lógica {pag} do PID {pid} com bit de referência 0 "
                                 f"({chances} segunda(s) chance(s) concedida(s)).")


ALGORITMOS = {"lru": LRU, "fifo": FIFO, "second_chance": SegundaChance}


# ------------------------------------------------------------ região dinâmica
class MemoriaVirtual:
    def __init__(self, num_molduras, processos):
        self.processos = processos
        self.molduras = [None] * num_molduras      # None ou (pid, pagina)
        self.ordem_carga = []                      # ordem FIFO das molduras ocupadas
        self.algoritmo = LRU
        self.relogio = 0                           # relógio lógico (ticks)
        self.acertos = 0
        self.faltas = 0

    def entrada(self, pid, pagina):
        return self.processos[pid].tabela_paginas[pagina]

    def usadas(self):
        return sum(1 for o in self.molduras if o is not None)

    def definir_algoritmo(self, nome):
        chave = nome.lower().replace(" ", "_").replace("-", "_")
        if chave not in ALGORITMOS:
            raise MemoriaError("Algoritmo inválido (use lru, second_chance ou fifo)")
        self.algoritmo = ALGORITMOS[chave]

    def criar(self, processo):
        n, desperdicio = fragmentacao_interna(processo.tamanho)
        processo.tabela_paginas = [Pagina() for _ in range(n)]
        print("[CRIAÇÃO DE PROCESSO NÃO CRÍTICO - MEMÓRIA VIRTUAL]")
        print(f"Tamanho do Processo : {fmt_kb(processo.tamanho)} ({processo.tamanho} Bytes)")
        print(f"Tamanho da Página   : {TAM_PAGINA // 1024} KB ({TAM_PAGINA} Bytes)")
        print(f"Cálculo de Páginas  : {processo.tamanho / TAM_PAGINA:.2f} -> Requer {n} Página(s) Lógica(s) (0 a {n - 1}).")
        print("\n--- ANÁLISE DE FRAGMENTAÇÃO INTERNA ---")
        usada_ultima = TAM_PAGINA - desperdicio
        if n > 1:
            if n - 1 <= 3:
                for p in range(n - 1):
                    print(f"Página Lógica {p} : {TAM_PAGINA} Bytes ocupados (100%)")
            else:
                print(f"Páginas Lógicas 0 a {n - 2} : {TAM_PAGINA} Bytes ocupados (100%)")
        print(f"Página Lógica {n - 1} : {usada_ultima} Bytes ocupados ({100 * usada_ultima / TAM_PAGINA:.0f}% de uso)")
        print(f"Fragmentação Interna Total: {desperdicio} Bytes de desperdício na Página Lógica {n - 1}.")
        print("Status: Tabela de Páginas gerada sem alocar molduras na RAM (Alocação por demanda).")

    def liberar(self, processo):
        molduras = 0
        for entrada in processo.tabela_paginas:
            if entrada.presente:
                self.molduras[entrada.moldura] = None
                if entrada.moldura in self.ordem_carga:
                    self.ordem_carga.remove(entrada.moldura)
                molduras += 1
        return molduras

    def acessar(self, processo, pagina, swap):
        """Devolve (hit, moldura)."""
        if not 0 <= pagina < len(processo.tabela_paginas):
            raise MemoriaError(
                f"Página lógica {pagina} inválida para '{processo.nome}' "
                f"(0 a {len(processo.tabela_paginas) - 1})")
        self.relogio += 1
        entrada = processo.tabela_paginas[pagina]
        if entrada.presente:
            entrada.ultimo_acesso = self.relogio
            entrada.bit_ref = 1
            self.acertos += 1
            return True, entrada.moldura
        self.faltas += 1
        return False, self._tratar_page_fault(processo, pagina, entrada, swap)

    def _tratar_page_fault(self, processo, pagina, entrada, swap):
        print(f"\n[PAGE FAULT DETECTADO]: Página Lógica {pagina} do '{processo.nome}' ausente na RAM!")
        moldura = next((i for i, o in enumerate(self.molduras) if o is None), None)
        if moldura is not None:
            print(f"Há moldura livre disponível (Moldura Física {moldura}); não é necessário substituir páginas.")
        else:
            print(f"Memória RAM cheia. Executando Substituição de Página (Algoritmo {self.algoritmo.nome}):")
            moldura, motivo = self.algoritmo.escolher_vitima(self)
            vpid, vpag = self.molduras[moldura]
            ventrada = self.entrada(vpid, vpag)
            print(f"- {motivo}")
            if ventrada.slot_swap is None:
                ventrada.slot_swap = swap.alocar_slot()
            print(f"- Removendo Página Lógica {vpag} do PID {vpid} da RAM -> Salvando no Swap (Disco, slot {ventrada.slot_swap}).")
            swap.gravar(ventrada.slot_swap, vpid, vpag)
            ventrada.presente = False
            ventrada.moldura = None
            self.molduras[moldura] = None
            if moldura in self.ordem_carga:
                self.ordem_carga.remove(moldura)

        if entrada.slot_swap is not None:
            print(f"- Trazendo Página Lógica {pagina} do Swap (slot {entrada.slot_swap}).")
            swap.ler(entrada.slot_swap, processo.pid, pagina)
        print(f"- Carregando Página Lógica {pagina} do {processo.nome} na Moldura Física {moldura} (RAM Dinâmica).")
        self.molduras[moldura] = (processo.pid, pagina)
        self.ordem_carga.append(moldura)
        entrada.presente = True
        entrada.moldura = moldura
        entrada.bit_ref = 1
        entrada.ultimo_acesso = self.relogio
        print(f"- Tabela de Páginas atualizada: Página Lógica {pagina} ---> Moldura Física {moldura}.")
        return moldura


# --------------------------------------------------------------- fachada única
class GerenciadorMemoria:
    def __init__(self, io, processos, num_molduras=NUM_MOLDURAS):
        self.swap = Swap(io)
        self.processos = processos
        self.reservada = AreaReservada()
        self.virtual = MemoriaVirtual(num_molduras, processos)
        self.comandos = 0

    # --- criação / encerramento
    def alocar(self, processo):
        if processo.tipo == "critical":
            bloco = self.reservada.alocar(processo)
            print(f"- Alocado de forma contígua na Área Reservada: "
                  f"[{fmt_mb(bloco.inicio)} até {fmt_mb(bloco.fim)}] ({fmt_kb(bloco.tamanho)})")
        else:
            self.virtual.criar(processo)

    def liberar(self, processo):
        if processo.tipo == "critical":
            inicio, fim, tamanho = self.reservada.liberar(processo.pid)
            print(f"[ENCERRAMENTO DE PROCESSO CRÍTICO] Processo '{processo.nome}' finalizado.")
            print(f"Área de {fmt_kb(tamanho)} no intervalo [{fmt_mb(inicio)} a {fmt_mb(fim)}] liberada na Área Reservada da RAM.")
        else:
            slots = [e.slot_swap for e in processo.tabela_paginas if e.slot_swap is not None]
            molduras = self.virtual.liberar(processo)
            for slot in slots:
                self.swap.liberar_slot(slot)
            print(f"[ENCERRAMENTO DE PROCESSO NÃO CRÍTICO] Processo '{processo.nome}' finalizado.")
            print(f"{molduras} moldura(s) liberada(s) na RAM Dinâmica e {len(slots)} slot(s) de swap liberado(s).")

    # --- acesso à memória virtual
    def traduzir(self, processo, pagina):
        if processo.tipo == "critical":
            raise MemoriaError(f"'{processo.nome}' é crítico: alocação contígua sem paginação "
                               f"(endereço físico base {fmt_mb(processo.base)}).")
        print("[TRADUÇÃO DE ENDEREÇO: PÁGINA LÓGICA -> MOLDURA FÍSICA]")
        hit, moldura = self.virtual.acessar(processo, pagina, self.swap)
        print(f"Solicitação: Página Lógica {pagina} -> Mapeada na Moldura Física {moldura} (RAM Dinâmica) "
              f"[{'HIT' if hit else 'MISS - carregada após page fault'}]")

    def executar_passo(self, processo, instrucao):
        m = re.search(r"(?:p[aá]gina|page)\s*(?:l[oó]gica\s*)?(\d+)", instrucao, re.IGNORECASE)
        if not m:
            raise MemoriaError('Instrução sem referência de página (ex.: "LOAD_DATA Página 2")')
        pagina = int(m.group(1))
        print("[CPU - REFERÊNCIA DE MEMÓRIA EM EXECUÇÃO]")
        if processo.tipo == "critical":
            print(f"{processo.nome} é crítico: acesso direto à Área Reservada (base {fmt_mb(processo.base)}), sem paginação.")
            return
        print(f"{processo.nome} requisita acesso à Página Lógica {pagina}...")
        hit, moldura = self.virtual.acessar(processo, pagina, self.swap)
        if hit:
            print(f"- Consulta Tabela de Páginas -> Página Lógica {pagina} na Moldura Física {moldura} [HIT]")
        else:
            print(f"- Página Lógica {pagina} agora presente na Moldura Física {moldura} [após PAGE FAULT]")

    # --- compactação e relatórios
    def compactar(self):
        print("[EXECUTANDO COMPACTAÇÃO DA ÁREA RESERVADA DA RAM]")
        print("Realocando blocos contíguos para eliminar a fragmentação externa...")
        movidos = self.reservada.compactar(self.processos)
        if not movidos:
            print("Nenhum bloco precisou ser movido.")
        for nome, i0, f0, i1, f1 in movidos:
            print(f"- Mapeamento de '{nome}': [{fmt_mb(i0)} a {fmt_mb(f0)}] -> Ajustado para: [{fmt_mb(i1)} a {fmt_mb(f1)}]")
        print("\n--- MAPA APÓS COMPACTAÇÃO ---")
        self.reservada.imprimir_mapa()
        print(f"Resultado: Fragmentação externa eliminada. Maior bloco contíguo: "
              f"{fmt_kb(self.reservada.diagnostico()['maior_bloco'])}.")

    def relatorio_fragmentacao(self):
        print("\n========== RELATÓRIO DE FRAGMENTAÇÃO ==========")
        print("-- Interna (memória virtual, páginas subutilizadas) --")
        total = 0
        normais = [p for p in self.processos.values() if p.tipo == "normal"]
        for p in normais:
            n, desperdicio = fragmentacao_interna(p.tamanho)
            total += desperdicio
            print(f"PID {p.pid} {p.nome}: {n} página(s), {desperdicio} Bytes desperdiçados na última página")
        if not normais:
            print("Nenhum processo normal ativo.")
        print(f"Total de fragmentação interna: {total} Bytes")
        d = self.reservada.diagnostico()
        print("-- Externa (área reservada, alocação contígua) --")
        print(f"Lacunas: {d['lacunas']} | Livre: {fmt_kb(d['livre_total'])} | Maior bloco: {fmt_kb(d['maior_bloco'])} | "
              f"Fragmentação externa: {'SIM' if d['externa'] else 'NÃO'}")
        print("===============================================\n")

    def contar_comando(self):
        self.comandos += 1
        if self.comandos % INTERVALO_RELATORIO == 0 and self.processos:
            print("[RELATÓRIO PERIÓDICO]")
            self.relatorio_fragmentacao()

    def status(self, reservada=False, virtual=False):
        if not reservada and not virtual:
            reservada = virtual = True
        if reservada:
            self.reservada.imprimir_mapa()
            self.reservada.imprimir_diagnostico()
        if virtual:
            if reservada:
                print()
            self._status_virtual()

    def _status_virtual(self):
        v = self.virtual
        total = len(v.molduras)
        usadas = v.usadas()
        print("--- MEMÓRIA VIRTUAL (REGIÃO DINÂMICA) ---")
        print(f"Molduras em uso : {usadas} de {total} ({100 * usadas / total:.1f}%) | Tamanho da página: {TAM_PAGINA} Bytes")
        print(f"Algoritmo de substituição : {v.algoritmo.nome}")
        acessos = v.acertos + v.faltas
        taxa = f"{100 * v.acertos / acessos:.1f}%" if acessos else "n/a"
        print(f"Acessos: {acessos} | Hits: {v.acertos} | Page faults: {v.faltas} | Taxa de acerto: {taxa}")
        print(f"Slots de swap em uso : {self.swap.slots_em_uso()}")
        normais = [p for p in self.processos.values() if p.tipo == "normal"]
        for p in normais:
            presentes = sum(1 for e in p.tabela_paginas if e.presente)
            print(f"PID {p.pid} {p.nome}: {presentes}/{len(p.tabela_paginas)} página(s) na RAM")
        if not normais:
            print("Nenhum processo normal ativo.")
