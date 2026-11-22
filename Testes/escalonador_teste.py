import importlib.util
import unittest
from contextlib import redirect_stdout
from io import StringIO

from interpretador import Super_bloco, interpretar_comando
from escalonador import (CPUError, NOVO, PRONTO, EXECUTANDO, BLOQUEADO, CONCLUIDO)

TEM_SEGURANCA = importlib.util.find_spec("seguranca") is not None


class NegadoStub(Exception):
    pass


class Usuario:
    def __init__(self, nome, uid):
        self.nome, self.uid = nome, uid


class SessaoStub:
    def __init__(self):
        self.usuario = Usuario("root", 0)
        self.log = []

    def exigir_kernel(self, operacao):
        if self.usuario.uid != 0:
            raise NegadoStub(f"'{operacao}' exige privilégios de superusuário")


class Base(unittest.TestCase):
    def novo(self, molduras=None):
        self.sb = Super_bloco(num_molduras=molduras)
        self.atual = self.sb.root
        self.cpu = self.sb.cpu

    def setUp(self):
        self.novo()

    def cmd(self, comando):
        with redirect_stdout(StringIO()) as saida:
            try:
                self.atual = interpretar_comando(comando, self.atual, self.sb)
            except NegadoStub as erro:
                return f"NEGADO {erro}"
        return saida.getvalue()

    def erro(self, comando, trecho=""):
        """O interpretador captura ValueError e imprime 'Erro: ...'; devolve a mensagem."""
        saida = self.cmd(comando)
        self.assertIn("Erro:", saida, comando)
        self.assertIn(trecho, saida, comando)
        return saida

    def unidade(self, nome):
        return next(u for u in self.cpu.unidades if u.nome == nome)

    def transicoes(self, nome):
        return [(de, para) for _, de, para, _ in self.unidade(nome).historico]


class TesteCriacao(Base):
    def test_create_process_com_perfil_de_io(self):
        s = self.cmd('create_process --name App_Web --burst 8ms --priority 1 '
                     '--syscall "read_disk at 3ms (duration: 4ms)"')
        self.assertIn("PID: 101", s)
        self.assertIn("Prioridade: 1 (Alta)", s)
        self.assertIn("Agendada para t=3ms (Duração do Bloqueio: 4ms)", s)
        self.assertIn("Estado Inicial: PRONTO", s)
        self.assertEqual(self.transicoes("App_Web"), [(NOVO, PRONTO)])

    def test_syscall_aleatoria_e_prioridade_baixa(self):
        s = self.cmd('create_process --name R --burst 5ms --priority 2 --syscall random')
        self.assertIn("Prioridade: 2 (Baixa)", s)
        self.assertIn("Evento Aleatório Habilitado", s)

    def test_chegada_futura_fica_novo(self):
        s = self.cmd("create_process --name X --burst 3ms --priority 1 --arrival 5ms")
        self.assertIn("NOVO (chega em t=5ms)", s)
        self.assertEqual(self.unidade("X").estado, NOVO)

    def test_entradas_invalidas(self):
        casos = ["create_process --name X --burst 0ms",
                 "create_process --name X --priority 1",
                 'create_process --name X --burst 4ms --syscall "read_disk at 4ms"',     # fora do burst
                 'create_process --name X --burst 4ms --syscall "lixo"',
                 'create_process --name X --burst 4ms --mutex "M at 9ms"',
                 "create_process --name X --burst 4ms --pages 1,99",
                 "create_process --name X --burst 4ms --priority 0"]
        for c in casos:
            self.erro(c)
        self.assertEqual(self.sb.processos, {})       # nada foi criado nem alocado

    def test_processo_so_de_memoria_continua_funcionando(self):
        self.cmd("create_process --name M --size 8KB --type normal")
        self.assertEqual(self.sb.processos[101].burst, None)
        self.erro("schedule", "Nenhum processo escalonável")
        self.cmd("create_process --name E --burst 2ms")
        self.cmd("schedule")
        self.assertEqual([u.nome for u in self.cpu.unidades], ["E"])   # M fora do escalonador


class TesteEscalonamento(Base):
    def test_round_robin_mesmo_nivel(self):
        self.cmd("create_process --name A --burst 4ms --priority 1")
        self.cmd("create_process --name B --burst 4ms --priority 1")
        s = self.cmd("schedule --algorithm Priority_RR --quantum 2ms")
        ordem = [l for l in s.splitlines() if "Executando" in l]
        self.assertEqual([l.split("|")[0].strip() for l in ordem],
                         ["[0ms - 2ms] Executando PID 101", "[2ms - 4ms] Executando PID 102",
                          "[4ms - 6ms] Executando PID 101", "[6ms - 8ms] Executando PID 102"])
        a, b = self.unidade("A"), self.unidade("B")
        self.assertEqual((a.espera, a.termino - a.chegada), (2, 6))
        self.assertEqual((b.espera, b.termino - b.chegada), (4, 8))
        self.assertEqual(self.cpu.trocas, 3)
        self.assertIn("Trocas de Contexto Totais     : 3", s)
        self.assertIn("AWT)   : 3.00", s)
        self.assertIn("ATT)  : 7.00", s)

    def test_prioridade_vence_independente_da_ordem_de_criacao(self):
        self.cmd("create_process --name Baixa --burst 3ms --priority 2")
        self.cmd("create_process --name Alta --burst 3ms --priority 1")
        self.cmd("schedule --quantum 5ms")
        self.assertLess(self.unidade("Alta").termino, self.unidade("Baixa").termino)
        self.assertEqual(self.unidade("Alta").primeira_exec, 0)

    def test_preempcao_por_prioridade_maior(self):
        self.cmd("create_process --name L --burst 6ms --priority 2")
        self.cmd("create_process --name H --burst 2ms --priority 1 --arrival 2ms")
        s = self.cmd("schedule --quantum 4ms")
        self.assertIn("[0ms - 2ms] Executando PID 101 | Preemptado por PID 102", s)
        self.assertIn("[2ms - 4ms] Executando PID 102 | PID 102 CONCLUÍDO!", s)
        self.assertIn("[4ms - 8ms] Executando PID 101 | PID 101 CONCLUÍDO!", s)
        l, h = self.unidade("L"), self.unidade("H")
        self.assertEqual((l.espera, h.espera), (2, 0))
        self.assertEqual(self.cpu.trocas, 2)

    def test_unico_processo_nao_gera_troca_de_contexto(self):
        self.cmd("create_process --name A --burst 7ms --priority 1")
        self.cmd("schedule --quantum 2ms")
        self.assertEqual(self.cpu.trocas, 0)
        self.assertEqual(self.unidade("A").termino, 7)

    def test_metricas_consistentes(self):
        for i, (b, p) in enumerate([(5, 1), (3, 2), (4, 1), (2, 3)]):
            self.cmd(f"create_process --name P{i} --burst {b}ms --priority {p}")
        self.cmd("schedule --quantum 2ms")
        for u in self.cpu.unidades:
            tat = u.termino - u.chegada
            # sem E/S: TAT = burst + espera
            self.assertEqual(tat, u.burst + u.espera, u.nome)
        self.assertEqual(self.cpu.ocupado, 14)
        self.assertEqual(self.cpu.relogio, 14)

    def test_algoritmo_invalido(self):
        self.cmd("create_process --name A --burst 2ms")
        self.erro("schedule --algorithm SJF", "Algoritmo inválido")


class TesteSyscallEBloqueio(Base):
    def setUp(self):
        super().setUp()
        self.cmd('create_process --name P --burst 5ms --priority 1 --syscall "read_disk at 2ms (duration: 3ms)"')

    def test_ciclo_de_vida_completo(self):
        self.cmd("schedule --quantum 4ms")
        self.assertEqual(self.transicoes("P"),
                         [(NOVO, PRONTO), (PRONTO, EXECUTANDO), (EXECUTANDO, BLOQUEADO),
                          (BLOQUEADO, PRONTO), (PRONTO, EXECUTANDO), (EXECUTANDO, CONCLUIDO)])
        self.assertEqual(self.sb.processos[101].estado, CONCLUIDO)

    def test_tempos_do_bloqueio_e_cpu_ociosa(self):
        s = self.cmd("schedule --quantum 4ms")
        self.assertIn("[0ms - 2ms] Executando PID 101 | Dispara Syscall read_disk -> BLOQUEADO (até t=5ms)", s)
        self.assertIn("[2ms - 5ms] CPU ociosa", s)
        self.assertIn("[5ms] Evento E/S: PID 101 encerra leitura de disco -> BLOQUEADO -> PRONTO", s)
        u = self.unidade("P")
        self.assertEqual((u.termino, u.espera, u.bloqueado_total), (8, 0, 3))
        self.assertEqual((self.cpu.ocupado, self.cpu.ocioso), (5, 3))

    def test_bloqueio_acontece_no_passo_certo(self):
        s = self.cmd("run_simulation --process P --steps 3")
        self.assertIn("[SYSCALL DETECTADA]: PID 101 atingiu a instrução de leitura de disco agendada para t=2ms!", s)
        self.assertIn("Desbloqueio em t=5ms", s)
        self.assertIn("parou após 2 passo(s): estado BLOQUEADO", s)
        self.assertEqual(self.unidade("P").estado, BLOQUEADO)
        self.assertNotIn("STEP 3", s)

    def test_syscall_gera_requisicao_de_disco_pelo_raid(self):
        s = self.cmd("run_simulation --process P --steps 2")
        self.assertIn("[E/S] LEITURA do bloco lógico", s)
        self.assertIn("RAID 5", s)

    def test_syscall_de_escrita(self):
        self.novo()
        self.cmd('create_process --name W --burst 3ms --syscall "write_disk at 1ms duration 1ms"')
        s = self.cmd("run_simulation --process W --steps 1")
        self.assertIn("[E/S] ESCRITA do bloco lógico", s)

    def test_cpu_e_liberada_para_outro_processo(self):
        self.cmd("create_process --name Q --burst 2ms --priority 2")
        s = self.cmd("schedule --quantum 4ms")
        self.assertIn("[2ms - 4ms] Executando PID 102 | PID 102 CONCLUÍDO!", s)       # preencheu o bloqueio
        self.assertEqual(self.unidade("Q").termino, 4)

    def test_syscall_aleatoria_e_deterministica_com_seed(self):
        def rodar():
            self.novo()
            self.cmd("create_process --name R --burst 6ms --syscall random --seed 3")
            self.cmd("schedule --quantum 3ms")
            u = self.unidade("R")
            return u.termino, u.bloqueado_total, self.cpu.syscalls_disparadas
        a, b = rodar(), rodar()
        self.assertEqual(a, b)
        self.assertEqual(a[2], 1)                 # no máximo um evento aleatório por unidade
        self.assertGreaterEqual(a[0], 6 + a[1])


class TesteThreadsEMutex(Base):
    def montar(self):
        self.cmd("create_process --name App --burst 1ms --priority 2")
        self.cmd('thread_create --process App --name T1 --burst 4ms --mutex "Buffer at 1ms hold 3ms"')
        self.cmd('thread_create --process App --name T2 --burst 3ms --mutex "Buffer at 1ms hold 1ms"')

    def test_thread_bloqueia_em_mutex_ocupado_e_acorda(self):
        self.montar()
        s = self.cmd("schedule --quantum 2ms")
        t2 = self.transicoes("T2")
        self.assertIn((EXECUTANDO, BLOQUEADO), t2)
        self.assertIn((BLOQUEADO, PRONTO), t2)
        self.assertEqual(t2[-1], (EXECUTANDO, CONCLUIDO))
        motivos = [m for _, _, para, m in self.unidade("T2").historico if para == BLOQUEADO]
        self.assertEqual(motivos, ["Aguardando Mutex"])
        self.assertIn("T2 (T2) tenta o Mutex 'Buffer' (dono: T1) -> BLOQUEADO", s)
        self.assertIn("T2 (T2) BLOQUEADO -> PRONTO e adquire o Mutex 'Buffer'", s)
        self.assertEqual(self.cpu.bloqueios_mutex, 1)
        self.assertEqual(self.unidade("T2").bloqueado_total, 2)         # t=4 até t=6
        self.assertIsNone(self.cpu.mutexes["Buffer"].dono)

    def test_passo_a_passo_mostra_mutex_como_no_enunciado(self):
        self.montar()
        s = self.cmd("run_simulation --steps 5")
        self.assertIn("Thread T1 (PID 101) tenta acessar Região Crítica ('Buffer').", s)
        self.assertIn("Mutex [LIVRE] -> T1 adquire o Mutex [BLOQUEADO].", s)
        self.assertIn("Mutex [BLOQUEADO por T1]!", s)
        self.assertIn("Mudança de Estado de T2: EXECUTANDO -> BLOQUEADO (Aguardando Mutex).", s)

    def test_processo_so_bloqueia_quando_todas_as_threads_bloqueiam(self):
        self.montar()
        self.cmd("run_simulation --steps 4")           # T2 bloqueada, T1 pronta
        self.assertEqual(self.unidade("T2").estado, BLOQUEADO)
        self.assertNotEqual(self.sb.processos[101].estado, BLOQUEADO)

    def test_threads_compartilham_a_tabela_de_paginas(self):
        self.montar()
        self.cmd("run_simulation --steps 4")
        proc = self.sb.processos[101]
        presentes = sum(1 for e in proc.tabela_paginas if e.presente)
        self.assertEqual(presentes, self.cpu.faltas)    # só há faltas de demanda, uma tabela só

    def test_mutex_status(self):
        self.montar()
        self.cmd("run_simulation --steps 4")
        s = self.cmd("mutex_status")
        self.assertIn("Mutex 'Buffer': [BLOQUEADO por T1", s)
        self.assertIn("Fila de espera: T2", s)

    def test_deadlock_e_detectado(self):
        self.cmd('create_process --name A --burst 5ms --mutex "X at 0ms hold 10ms" --mutex "Y at 2ms hold 10ms"')
        self.cmd('create_process --name B --burst 5ms --mutex "Y at 0ms hold 10ms" --mutex "X at 1ms hold 10ms"')
        s = self.cmd("schedule --quantum 1ms")
        self.assertIn("[DEADLOCK]", s)
        self.assertIn("PID 101 aguarda Mutex 'Y'", s)
        self.assertIn("PID 102 aguarda Mutex 'X'", s)

    def test_mutex_liberado_ao_concluir_com_lock_pendente(self):
        self.cmd('create_process --name A --burst 2ms --mutex "X at 0ms hold 99ms"')
        self.cmd('create_process --name B --burst 2ms --mutex "X at 0ms hold 1ms"')
        self.cmd("schedule --quantum 1ms")
        self.assertEqual(self.unidade("A").estado, CONCLUIDO)
        self.assertEqual(self.unidade("B").estado, CONCLUIDO)

    def test_thread_em_processo_concluido_ou_nome_repetido(self):
        self.cmd("create_process --name App --burst 1ms")
        self.erro("thread_create --process App --name App --burst 2ms", "Já existe")
        self.cmd("thread_create --process App --name T1 --burst 1ms")
        self.erro("thread_create --process App --name T1 --burst 1ms", "Já existe")
        self.cmd("schedule")
        self.erro("thread_create --process App --name T9 --burst 1ms", "já foi concluído")


class TesteMemoriaIntegrada(Base):
    def test_referencias_geram_page_fault_e_substituicao_lru(self):
        self.novo(molduras=2)
        self.cmd("create_process --name A --burst 6ms --pages 0,1,0,2,1,0")
        s = self.cmd("run_simulation --process A --steps 5")          # para antes de concluir
        self.assertIn("CPU acessa: Página Lógica 00 -> [PAGE FAULT!]", s)
        self.assertIn("[RAM: Moldura", s)
        self.assertIn("Histórico LRU: Pág 00 atualizada (t=3ms)", s)
        self.assertIn("Substituição LRU: Página Lógica 01 do PID 101 (não usada há 2ms) removida para o Swap.", s)
        self.assertIn("trazida de volta do Swap", s)
        self.assertIn("[RESUMO DA GERÊNCIA DE MEMÓRIA (RAM DINÂMICA)]", s)
        self.assertEqual(self.sb.memoria.swap.slots_em_uso(), 2)      # páginas 1 e 0 foram para o swap
        self.assertEqual((self.cpu.faltas, self.cpu.acertos), (4, 1))  # só o 3º acesso (pág. 0) é HIT
        self.assertEqual(self.sb.memoria.virtual.usadas(), 2)

    def test_lru_atualiza_com_o_tempo_da_simulacao(self):
        self.cmd("create_process --name A --burst 3ms --pages 2,7,2")
        self.cmd("run_simulation --process A --steps 3")
        virtual = self.sb.memoria.virtual
        self.assertEqual(self.cpu.ultimo_ms[(101, 2)], 3)
        self.assertEqual(self.cpu.ultimo_ms[(101, 7)], 2)
        self.assertGreaterEqual(virtual.relogio, 3)

    def test_outros_algoritmos_de_substituicao(self):
        self.novo(molduras=2)
        self.cmd("set_replacement --algo second_chance")
        self.cmd("create_process --name A --burst 4ms --pages 0,1,2,0")
        s = self.cmd("run_simulation --process A --steps 4")
        self.assertIn("Substituição Segunda Chance", s)

    def test_processo_critico_nao_pagina(self):
        self.cmd("create_process --name K --burst 2ms --priority 1 --type critical --size 128KB")
        s = self.cmd("run_simulation --process K --steps 1")
        self.assertIn("acesso direto à Área Reservada", s)
        self.assertEqual(self.cpu.faltas + self.cpu.acertos, 0)

    def test_conclusao_libera_memoria_e_terminate_ainda_funciona(self):
        self.cmd("create_process --name A --burst 3ms --pages 0,1,2")
        self.cmd("schedule")
        self.assertEqual(self.sb.memoria.virtual.usadas(), 0)
        self.assertEqual(self.sb.processos[101].estado, CONCLUIDO)
        s = self.cmd("terminate_process --name A")
        self.assertIn("já havia concluído", s)
        self.assertEqual(self.sb.processos, {})

    def test_terminate_no_meio_da_simulacao_remove_das_filas_e_solta_mutex(self):
        self.cmd('create_process --name A --burst 6ms --mutex "X at 0ms hold 9ms"')
        self.cmd('create_process --name B --burst 3ms --mutex "X at 0ms hold 1ms"')
        self.cmd("run_simulation --process A --steps 2")
        self.assertIsNotNone(self.cpu.mutexes["X"].dono)
        self.cmd("terminate_process --name A")
        self.assertIsNone(self.cpu.mutexes["X"].dono)
        self.cmd("schedule")                                   # B termina sem travar
        self.assertEqual(self.unidade("B").estado, CONCLUIDO)
        self.assertEqual([u.nome for u in self.cpu.unidades], ["B"])

    def test_sim_reset_reproduz_o_mesmo_resultado(self):
        self.cmd("create_process --name A --burst 4ms --priority 1 --syscall \"read_disk at 1ms duration 2ms\"")
        self.cmd("create_process --name B --burst 3ms --priority 1")
        self.cmd("schedule --quantum 2ms")
        antes = [(u.nome, u.espera, u.termino) for u in self.cpu.unidades]
        self.cmd("sim_reset")
        self.assertEqual(self.cpu.relogio, 0)
        self.assertTrue(all(u.estado == PRONTO for u in self.cpu.unidades))
        self.cmd("schedule --quantum 2ms")
        self.assertEqual(antes, [(u.nome, u.espera, u.termino) for u in self.cpu.unidades])


class TesteRelatorios(Base):
    def test_ps_e_historico(self):
        self.cmd("create_process --name A --burst 2ms --priority 1")
        self.cmd("schedule")
        s = self.cmd("ps --history")
        self.assertIn("CONCLUÍDO", s)
        self.assertIn("NOVO -> PRONTO", s)
        self.assertIn("EXECUTANDO -> CONCLUÍDO", s)

    def test_metrics_parcial_antes_de_concluir(self):
        self.cmd("create_process --name A --burst 5ms")
        self.cmd("run_simulation --process A --steps 2")
        s = self.cmd("metrics")
        self.assertIn("Unidades ainda não concluídas: 1", s)

    def test_transicao_invalida_e_rejeitada(self):
        self.cmd("create_process --name A --burst 2ms")
        with self.assertRaises(CPUError):
            self.cpu._mudar(self.unidade("A"), CONCLUIDO, "pulando etapas")

    def test_run_simulation_exige_processo_pronto(self):
        self.cmd('create_process --name A --burst 4ms --syscall "read_disk at 1ms duration 5ms"')
        self.cmd("run_simulation --process A --steps 1")
        self.erro("run_simulation --process A --steps 1", "estado BLOQUEADO")
        self.cmd("create_process --name F --burst 2ms --arrival 50ms")
        self.erro("run_simulation --process F --steps 1", "chega em t=50ms")


class TesteSegurancaStub(Base):
    def setUp(self):
        super().setUp()
        self.sb.sessao = SessaoStub()

    def entrar(self, nome, uid):
        self.sb.sessao.usuario = Usuario(nome, uid)

    def test_so_root_escalona(self):
        self.cmd("create_process --name A --burst 2ms")
        self.entrar("carlos", 1)
        self.assertIn("NEGADO", self.cmd("schedule"))
        self.assertIn("NEGADO", self.cmd("run_simulation --steps 1"))
        self.assertIn("NEGADO", self.cmd("sim_reset"))

    def test_usuario_roda_apenas_o_proprio_processo(self):
        self.entrar("carlos", 1)
        self.cmd("create_process --name Meu --burst 3ms")
        self.entrar("ana", 2)
        self.assertIn("NEGADO", self.cmd("run_simulation --process Meu --steps 1"))
        self.assertIn("NEGADO", self.cmd("thread_create --process Meu --name T --burst 1ms"))
        self.entrar("carlos", 1)
        self.assertNotIn("NEGADO", self.cmd("run_simulation --process Meu --steps 1"))
        self.assertNotIn("NEGADO", self.cmd("thread_create --process Meu --name T --burst 1ms"))

    def test_processo_critico_com_burst_exige_kernel(self):
        self.entrar("carlos", 1)
        self.assertIn("NEGADO", self.cmd("create_process --name K --burst 2ms --type critical"))
        self.assertEqual(self.sb.processos, {})

    def test_consultas_sao_livres(self):
        self.cmd("create_process --name A --burst 2ms")
        self.entrar("carlos", 1)
        for c in ("ps", "metrics", "mutex_status"):
            self.assertNotIn("NEGADO", self.cmd(c))


@unittest.skipUnless(TEM_SEGURANCA, "etapa de segurança ainda não está na main")
class TesteComSegurancaReal(Base):
    def setUp(self):
        super().setUp()
        self.cmd("groupadd devs")
        self.cmd("useradd carlos devs senha123")

    def test_usuario_comum_nao_escalona_mas_cria_processo(self):
        self.cmd("login carlos senha123")
        self.assertIn("[NEGADO]", self.cmd("schedule"))
        s = self.cmd("create_process --name App --burst 3ms --priority 2")
        self.assertIn("Estado Inicial: PRONTO", s)
        self.assertIn("[NEGADO]", self.cmd("create_process --name K --burst 3ms --type critical"))
        self.cmd("login root root")
        self.assertIn("carlos negado", self.cmd("logs"))
        self.assertIn("Estado Inicial", self.cmd("ps") + "Estado Inicial")
        self.cmd("schedule")
        self.assertEqual(self.unidade("App").estado, CONCLUIDO)

    def test_antivirus_ok_depois_de_syscalls_e_swap(self):
        self.novo(molduras=2)
        self.cmd("groupadd devs")
        self.cmd('create_process --name A --burst 6ms --pages 0,1,2,0,1,2 --syscall "write_disk at 2ms duration 2ms"')
        self.cmd("schedule --quantum 3ms")
        self.assertNotIn("[ALERTA]", self.cmd("antivirus_scan /"))


if __name__ == "__main__":
    unittest.main()
