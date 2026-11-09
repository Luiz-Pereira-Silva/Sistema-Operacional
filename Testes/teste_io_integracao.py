
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
from interpretador import Super_bloco, interpretar_comando

class TestIntegracaoIO(unittest.TestCase):
    def setUp(self):
        self.sb = Super_bloco()
        self.atual = self.sb.root
        self.io = self.sb.gerenciador_io

    def executar(self, comando):
        with redirect_stdout(StringIO()):
            self.atual = interpretar_comando(comando, self.atual, self.sb)

    def test_touch_gera_escrita_de_metadados(self):
        print("\n========== TESTE TOUCH ==========")

        with patch.object(self.io.raid, "write_block", wraps=self.io.raid.write_block) as escrita, \
             patch.object(self.io.scheduler, "schedule", wraps=self.io.scheduler.schedule) as escalonamento:
            self.executar("touch / teste.txt")

        blocos = [c.args[0] for c in escrita.call_args_list]

        print("Comando: touch / teste.txt")
        print("Blocos escritos:", blocos)
        print("Escalonador FCFS acionado:", escalonamento.called)
        print("Escrita de metadados:", any(b >= 25 for b in blocos))

        self.assertTrue(escrita.called)
        self.assertTrue(escalonamento.called)
        self.assertTrue(any(b >= 25 for b in blocos))

    def test_echo_gera_escrita_de_dados(self):
        print("\n========== TESTE ECHO ==========")
        self.executar("touch / teste.txt")

        with patch.object(self.io.raid, "write_block", wraps=self.io.raid.write_block) as escrita, \
             patch.object(self.io.scheduler, "schedule", wraps=self.io.scheduler.schedule) as escalonamento:
            self.executar("echo / teste.txt Olá mundo")

        inode = self.sb.tabela_inodes[0]
        blocos = [c.args[0] for c in escrita.call_args_list]
        dados_corretos = all(
            self.io.raid.read_block(b) == self.sb.blocos[b].tobytes()
            for b in inode.blocos
        )

        print("Comando: echo / teste.txt Olá mundo")
        print("Blocos de dados:", inode.blocos)
        print("Blocos escritos:", blocos)
        print("Escalonador FCFS acionado:", escalonamento.called)
        print("Dados gravados corretamente:", dados_corretos)

        self.assertTrue(escrita.called)
        self.assertTrue(escalonamento.called)
        self.assertTrue(any(b in inode.blocos for b in blocos))
        self.assertTrue(any(b >= 25 for b in blocos))
        self.assertTrue(dados_corretos)

    def test_cat_gera_leitura_no_raid(self):
        print("\n========== TESTE CAT ==========")
        self.executar("touch / teste.txt")
        self.executar("echo / teste.txt Olá mundo")
        inode = self.sb.tabela_inodes[0]

        with patch.object(self.io.raid, "read_block", wraps=self.io.raid.read_block) as leitura, \
             patch.object(self.io.scheduler, "schedule", wraps=self.io.scheduler.schedule) as escalonamento:
            with redirect_stdout(StringIO()) as saida:
                interpretar_comando("cat / teste.txt", self.atual, self.sb)

        blocos = [c.args[0] for c in leitura.call_args_list]
        conteudo = saida.getvalue().strip().splitlines()[-1]

        print("Comando: cat / teste.txt")
        print("Blocos solicitados:", inode.blocos)
        print("Blocos lidos:", blocos)
        print("Escalonador FCFS acionado:", escalonamento.called)
        print("Conteúdo recuperado:", conteudo)

        self.assertTrue(leitura.called)
        self.assertTrue(escalonamento.called)
        self.assertEqual(conteudo, "Olá mundo")

        for bloco in inode.blocos:
            self.assertIn(bloco, blocos)

if __name__ == "__main__":
    unittest.main(verbosity=2)
