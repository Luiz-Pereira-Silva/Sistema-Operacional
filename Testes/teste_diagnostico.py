import unittest
from contextlib import redirect_stdout
from io import StringIO

from interpretador import Super_bloco, interpretar_comando
from disk_simulator import SSTFScheduler, FCFSScheduler, IORequest


class TestDiagnostico(unittest.TestCase):
    def setUp(self):
        self.sb = Super_bloco()
        self.atual = self.sb.root
        for cmd in ('mkdir / sistema', 'mkdir /sistema logs', 'touch /sistema/logs app.log',
                    'echo /sistema/logs app.log "0123456789ABCDEFGHIJ0123456789ABCDE"'):
            self.rodar(cmd)

    def rodar(self, comando):
        saida = StringIO()
        with redirect_stdout(saida):
            self.atual = interpretar_comando(comando, self.atual, self.sb)
        return saida.getvalue()

    # ---------------- etapa 1
    def test_tree_mostra_hierarquia(self):
        saida = self.rodar("tree")
        self.assertIn("sistema/ [DIR]", saida)
        self.assertIn("logs/ [DIR]", saida)
        self.assertIn("app.log (35 B) [ARQ]", saida)

    def test_fs_status_ocupacao_e_fragmentacao_interna(self):
        saida = self.rodar("fs_status --details")
        self.assertIn("Bloco 02 [DADO]  : '/sistema/logs/app.log' (Bloco 3/3 - 3 bytes ocupados)", saida)
        self.assertIn("alocado 48 B (3 bloco(s) de 16 B)", saida)
        self.assertIn("desperdício 13 B", saida)
        self.assertIn("Fragmentação Interna Total       : 13 bytes", saida)
        self.assertIn("Fragmentação Externa             : 0 bytes", saida)
        self.assertIn("Necessidade de Compactação       : NÃO", saida)

    def test_fs_status_detecta_lacunas_livres_dispersas(self):
        self.rodar("touch / b.txt"); self.rodar('echo / b.txt "x"')
        self.rodar("rm /sistema/logs app.log")            # libera 0..2, b.txt fica no bloco 3
        self.rodar("touch / c.txt"); self.rodar('echo / c.txt "y"')
        saida = self.rodar("fs_status")
        self.assertIn("lacuna(s)", saida)
        self.assertIn("Maior lacuna contígua", saida)

    # ---------------- etapa 2: RAID
    def test_raid_test_recupera_e_reconstroi(self):
        saida = self.rodar("raid_test 1")
        self.assertIn("Falha forçada no Disco 1", saida)
        self.assertIn("Reconstrução [OK]", saida)
        self.assertNotIn("FALHOU", saida)
        self.assertTrue(all(d.online for d in self.sb.gerenciador_io.raid.disks))

    def test_leitura_com_disco_falho_via_xor(self):
        self.rodar("raid_fail 0")
        self.assertIn("0123456789ABCDEFGHIJ0123456789ABCDE", self.rodar("cat /sistema/logs app.log"))
        self.assertIn("MODO DEGRADADO", self.rodar("raid_status"))
        self.rodar("raid_rebuild 0")
        self.assertTrue(all(d.online for d in self.sb.gerenciador_io.raid.disks))

    def test_dois_discos_falhos_negado(self):
        self.rodar("raid_fail 0")
        self.assertIn("Erro:", self.rodar("raid_fail 1"))

    def test_argumentos_invalidos(self):
        self.assertIn("Erro:", self.rodar("raid_fail"))
        self.assertIn("Erro:", self.rodar("raid_fail 9"))
        self.assertIn("Erro:", self.rodar("disk_sched xyz"))

    # ---------------- etapa 2: escalonamento
    def test_sstf_exemplo_do_enunciado(self):
        r = SSTFScheduler.schedule([IORequest(track=t) for t in (98, 183, 37, 122, 14)], 53)
        self.assertEqual(r.order, [53, 37, 14, 98, 122, 183])
        self.assertEqual(r.total_movement, 208)

    def test_sstf_melhor_que_fcfs_no_exemplo(self):
        reqs = [IORequest(track=t) for t in (98, 183, 37, 122, 14)]
        self.assertLess(SSTFScheduler.schedule(reqs, 53).total_movement,
                        FCFSScheduler.schedule(reqs, 53).total_movement)

    def test_troca_de_escalonador_afeta_o_io(self):
        self.rodar("disk_sched sstf")
        self.assertIn("ESCALONAMENTO SSTF", self.rodar("touch / n.txt"))

    def test_demo_nao_altera_estado(self):
        cabeca = self.sb.gerenciador_io.cabeca
        saida = self.rodar('disk_sched --demo "98,183,37,122,14" --head 53 --algorithm sstf')
        self.assertIn("= 208 trilhas", saida)
        self.assertEqual(self.sb.gerenciador_io.cabeca, cabeca)

    # ---------------- segurança
    def test_usuario_comum_nao_usa_comandos_de_kernel(self):
        self.rodar("groupadd devs"); self.rodar("useradd carlos devs abc"); self.rodar("login carlos abc")
        for cmd in ("fs_status", "raid_fail 0", "raid_rebuild 0", "raid_test", "disk_sched sstf"):
            self.assertIn("[NEGADO]", self.rodar(cmd), cmd)
        self.assertTrue(all(d.online for d in self.sb.gerenciador_io.raid.disks))
        self.assertIn("[ÁRVORE", self.rodar("tree"))      # leitura segue permitida


if __name__ == "__main__":
    unittest.main(verbosity=2)
