
import unittest
from contextlib import redirect_stdout
from io import StringIO
from interpretador import Super_bloco, interpretar_comando
from swap import SWAP_BASE_LBA
from memoria import parse_tamanho, fragmentacao_interna, MemoriaError


class TesteMemoria(unittest.TestCase):
    def novo(self, molduras=128):
        self.sb = Super_bloco(num_molduras=molduras)
        self.atual = self.sb.root

    def executar(self, comando):
        with redirect_stdout(StringIO()) as saida:
            self.atual = interpretar_comando(comando, self.atual, self.sb)
        return saida.getvalue()

    def verificar(self, descricao, resultado):
        print(f"{descricao}: {'OK' if resultado else 'FALHOU'}")
        self.assertTrue(resultado)

    def setUp(self):
        self.novo()

    def processo(self, nome):
        return next(p for p in self.sb.processos.values() if p.nome == nome)

    # ------------------------------------------------------------ utilitários
    def test_parse_tamanho(self):
        print("\n========== TESTE PARSE DE TAMANHO ==========")
        self.verificar("512KB", parse_tamanho("512KB") == 512 * 1024)
        self.verificar("1MB", parse_tamanho("1MB") == 1024 * 1024)
        self.verificar("100B", parse_tamanho("100b") == 100)
        with self.assertRaises(MemoriaError):
            parse_tamanho("10XB")

    def test_fragmentacao_interna_calculo(self):
        print("\n========== TESTE FRAGMENTAÇÃO INTERNA (CÁLCULO) ==========")
        self.verificar("10 KB -> 3 páginas, 2048 B", fragmentacao_interna(10 * 1024) == (3, 2048))
        self.verificar("8 KB -> 2 páginas, 0 B", fragmentacao_interna(8 * 1024) == (2, 0))

    # --------------------------------------------- Exemplo 4.1 (área reservada)
    def test_exemplo_4_1_reservada_fragmentacao_e_compactacao(self):
        print("\n========== TESTE EXEMPLO 4.1 ==========")
        r = self.sb.memoria.reservada
        saida = self.executar("create_process --name Kernel_DiskDriver --size 512KB --type critical")
        self.verificar("Disk em [1.0 MB até 1.5 MB]", "[1.0 MB até 1.5 MB] (512 KB)" in saida)
        saida = self.executar("create_process --name Kernel_NetDriver --size 1024KB --type critical")
        self.verificar("Net em [1.5 MB até 2.5 MB]", "[1.5 MB até 2.5 MB] (1024 KB)" in saida)
        self.executar("create_process --name Kernel_CryptoEngine --size 512KB --type critical")
        self.verificar("Crypto base em 2.5 MB", self.processo("Kernel_CryptoEngine").base == 2560 * 1024)

        saida = self.executar("terminate_process --name Kernel_NetDriver")
        self.verificar("Mensagem de encerramento crítico", "[ENCERRAMENTO DE PROCESSO CRÍTICO]" in saida)

        d = r.diagnostico()
        self.verificar("2 lacunas", d["lacunas"] == 2)
        self.verificar("Livre total 2048 KB", d["livre_total"] == 2048 * 1024)
        self.verificar("Maior bloco 1024 KB", d["maior_bloco"] == 1024 * 1024)
        self.verificar("Fragmentação externa detectada", d["externa"])

        saida = self.executar("memory_status --reserved")
        self.verificar("Status aponta fragmentação SIM", "SIM (2 fragmentos" in saida)

        saida = self.executar("create_process --name Grande --size 1536KB --type critical")
        self.verificar("Contígua de 1536 KB falha", "Fragmentação externa" in saida and "Grande" not in str(self.sb.processos))

        saida = self.executar("memory_compact --reserved")
        self.verificar("Crypto movido para 1.5 MB", "[2.5 MB a 3.0 MB] -> Ajustado para: [1.5 MB a 2.0 MB]" in saida)
        d = r.diagnostico()
        self.verificar("Após compactar: 1 lacuna", d["lacunas"] == 1 and not d["externa"])
        self.verificar("Maior bloco 2048 KB", d["maior_bloco"] == 2048 * 1024)
        self.verificar("base do processo atualizada", self.processo("Kernel_CryptoEngine").base == 1536 * 1024)

        saida = self.executar("create_process --name Grande --size 1536KB --type critical")
        self.verificar("Contígua de 1536 KB passa após compactação", "Alocado de forma contígua" in saida)

    def test_liberacao_funde_lacunas_vizinhas(self):
        print("\n========== TESTE FUSÃO DE LACUNAS ==========")
        for n in ("A", "B", "C"):
            self.executar(f"create_process --name {n} --size 256KB --type critical")
        self.executar("terminate_process --name A")
        self.executar("terminate_process --name B")
        r = self.sb.memoria.reservada
        d = r.diagnostico()
        self.verificar("A+B liberados viram uma única lacuna de 512 KB",
                       r.blocos[1].livre and r.blocos[1].tamanho == 512 * 1024)
        self.verificar("Restam 2 lacunas (512 KB e 2304 KB)",
                       d["lacunas"] == 2 and d["livre_total"] == (512 + 2304) * 1024)
        self.verificar("Núcleo base nunca é liberado",
                       self.sb.memoria.reservada.blocos[0].nome == "Núcleo Base do SO")

    def test_reservada_cheia(self):
        print("\n========== TESTE ÁREA RESERVADA CHEIA ==========")
        saida = self.executar("create_process --name Enorme --size 4MB --type critical")
        self.verificar("Rejeita pedido maior que o livre", "insuficiente" in saida and not self.sb.processos)

    # ------------------------------------------------ Exemplo 4.2 (memória virtual)
    def test_exemplo_4_2_criacao_paginada(self):
        print("\n========== TESTE EXEMPLO 4.2 (CRIAÇÃO) ==========")
        saida = self.executar("create_process --name App_Navegador --size 10KB --type normal")
        p = self.processo("App_Navegador")
        self.verificar("3 páginas lógicas", len(p.tabela_paginas) == 3)
        self.verificar("2048 B de fragmentação interna", "2048 Bytes de desperdício" in saida)
        self.verificar("Nenhuma moldura alocada (demanda)", self.sb.memoria.virtual.usadas() == 0)
        self.verificar("Nenhuma página presente", not any(e.presente for e in p.tabela_paginas))

    def test_traducao_miss_depois_hit(self):
        print("\n========== TESTE TRADUÇÃO MISS -> HIT ==========")
        self.executar("create_process --name App --size 10KB --type normal")
        s1 = self.executar("translate_address --process App --page 1")
        s2 = self.executar("translate_address --process App --page 1")
        self.verificar("Primeiro acesso: page fault", "PAGE FAULT" in s1 and "MISS" in s1)
        self.verificar("Segundo acesso: HIT", "[HIT]" in s2 and "PAGE FAULT" not in s2)
        v = self.sb.memoria.virtual
        self.verificar("Contadores", (v.faltas, v.acertos) == (1, 1))

    def test_pagina_invalida_e_processo_critico(self):
        print("\n========== TESTE ERROS DE ENDEREÇO ==========")
        self.executar("create_process --name App --size 10KB --type normal")
        self.executar("create_process --name Kernel_X --size 64KB --type critical")
        s = self.executar("translate_address --process App --page 9")
        self.verificar("Página fora do intervalo", "inválida" in s)
        s = self.executar("translate_address --process Kernel_X --page 0")
        self.verificar("Crítico não usa paginação", "sem paginação" in s)
        s = self.executar("translate_address --process Fantasma --page 0")
        self.verificar("Processo inexistente", "inexistente" in s)

    # ------------------------------------------------ page fault, LRU e swap
    def test_page_fault_lru_grava_swap_no_raid(self):
        print("\n========== TESTE PAGE FAULT + LRU + SWAP NO RAID ==========")
        self.novo(molduras=2)
        self.executar("create_process --name A --size 12KB --type normal")  # 3 páginas
        self.executar('execute_step --process A --instruction "LOAD Página 0"')
        self.executar('execute_step --process A --instruction "LOAD Página 1"')
        self.executar('execute_step --process A --instruction "LOAD Página 0"')  # página 0 mais recente
        saida = self.executar('execute_step --process A --instruction "LOAD Página 2"')

        p = self.processo("A")
        self.verificar("RAM cheia detectada", "Memória RAM cheia" in saida and "Algoritmo LRU" in saida)
        self.verificar("LRU removeu a página 1", not p.tabela_paginas[1].presente and p.tabela_paginas[0].presente)
        self.verificar("Página 2 carregada", p.tabela_paginas[2].presente)
        slot = p.tabela_paginas[1].slot_swap
        self.verificar("Slot de swap atribuído", slot is not None)
        bloco = self.sb.gerenciador_io.raid.read_block(SWAP_BASE_LBA + slot)
        self.verificar("Swap gravado no RAID 5", bloco.rstrip(b"\x00") == f"{p.pid},1".encode())
        self.verificar("Passou pelo escalonador FCFS", "ESCALONAMENTO FCFS" in saida)

        saida = self.executar('execute_step --process A --instruction "LOAD Página 1"')
        self.verificar("Página volta do swap", "do Swap" in saida and p.tabela_paginas[1].presente)

    def test_substituicao_entre_processos(self):
        print("\n========== TESTE SUBSTITUIÇÃO GLOBAL ==========")
        self.novo(molduras=1)
        self.executar("create_process --name A --size 4KB --type normal")
        self.executar("create_process --name B --size 4KB --type normal")
        self.executar("translate_address --process A --page 0")
        saida = self.executar("translate_address --process B --page 0")
        self.verificar("Vítima é do PID 1", "Página Lógica 0 do PID 1" in saida)
        self.verificar("A saiu da RAM, B entrou",
                       not self.processo("A").tabela_paginas[0].presente and self.processo("B").tabela_paginas[0].presente)

    def cenario_lru_vs_segunda_chance(self, algo):
        self.novo(molduras=3)
        self.executar(f"set_replacement --algo {algo}")
        self.executar("create_process --name A --size 16KB --type normal")  # 4 páginas
        for pag in (0, 1, 2, 0, 3):
            self.executar(f'execute_step --process A --instruction "LOAD Página {pag}"')
        return [e.presente for e in self.processo("A").tabela_paginas]

    def test_lru_difere_de_segunda_chance(self):
        print("\n========== TESTE LRU x SEGUNDA CHANCE ==========")
        lru = self.cenario_lru_vs_segunda_chance("lru")
        sc = self.cenario_lru_vs_segunda_chance("second_chance")
        self.verificar("LRU remove a página 1", lru == [True, False, True, True])
        self.verificar("Segunda Chance remove a página 0", sc == [False, True, True, True])

    def test_fifo_e_algoritmo_invalido(self):
        print("\n========== TESTE FIFO E ALGORITMO INVÁLIDO ==========")
        fifo = self.cenario_lru_vs_segunda_chance("fifo")
        self.verificar("FIFO remove a mais antiga (página 0)", fifo == [False, True, True, True])
        s = self.executar("set_replacement --algo xyz")
        self.verificar("Algoritmo inválido rejeitado", "Algoritmo inválido" in s)

    def test_encerrar_processo_normal_libera_molduras_e_swap(self):
        print("\n========== TESTE ENCERRAR PROCESSO NORMAL ==========")
        self.novo(molduras=1)
        self.executar("create_process --name A --size 8KB --type normal")
        self.executar("translate_address --process A --page 0")
        self.executar("translate_address --process A --page 1")   # expulsa a 0 para o swap
        self.verificar("Um slot de swap em uso", self.sb.memoria.swap.slots_em_uso() == 1)
        self.executar("terminate_process --name A")
        self.verificar("Molduras liberadas", self.sb.memoria.virtual.usadas() == 0)
        self.verificar("Swap liberado", self.sb.memoria.swap.slots_em_uso() == 0)
        self.verificar("Processo removido da tabela", not self.sb.processos)
        self.executar("create_process --name B --size 4KB --type normal")
        self.verificar("Novo processo reaproveita a RAM", self.sb.memoria.virtual.usadas() == 0)

    # ----------------------------------------------------------- relatórios
    def test_relatorio_periodico(self):
        print("\n========== TESTE RELATÓRIO PERIÓDICO ==========")
        saidas = [self.executar("create_process --name A --size 10KB --type normal")]
        for _ in range(4):
            saidas.append(self.executar("memory_status --virtual"))
        self.verificar("Relatório no 5º comando de memória", "RELATÓRIO PERIÓDICO" in saidas[-1])
        self.verificar("Não aparece antes", all("RELATÓRIO PERIÓDICO" not in s for s in saidas[:-1]))
        self.verificar("Traz fragmentação interna", "2048 Bytes" in saidas[-1])

    def test_status_ocupacao(self):
        print("\n========== TESTE OCUPAÇÃO ==========")
        self.executar("create_process --name K --size 1MB --type critical")
        self.executar("create_process --name A --size 8KB --type normal")
        self.executar("translate_address --process A --page 0")
        saida = self.executar("memory_status")
        self.verificar("Mostra área reservada", "ÁREA CRÍTICA/RESERVADA" in saida and "50.0%" in saida)
        self.verificar("Mostra memória virtual", "Molduras em uso : 1 de 128" in saida)

    def test_parametros_obrigatorios(self):
        print("\n========== TESTE PARÂMETROS ==========")
        self.verificar("create_process sem --size", "obrigatório" in self.executar("create_process --name A --type normal"))
        self.verificar("tipo inválido", "Tipo de processo inválido" in self.executar("create_process --name A --size 4KB --type xpto"))
        self.executar("create_process --name A --size 4KB --type normal")
        self.verificar("nome duplicado", "Já existe" in self.executar("create_process --name A --size 4KB --type normal"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
