import unittest
from contextlib import redirect_stdout
from io import StringIO
from interpretador import Super_bloco, interpretar_comando


class TestCriptografia(unittest.TestCase):
    def setUp(self):
        self.sb = Super_bloco()
        self.atual = self.sb.root
        self.executar("touch / segredo.txt")
        self.executar("echo / segredo.txt Olá mundo secreto")

    def executar(self, comando):
        with redirect_stdout(StringIO()) as saida:
            self.atual = interpretar_comando(comando, self.atual, self.sb)
        return saida.getvalue()

    def conteudo_no_raid(self):
        inode = self.sb.tabela_inodes[0]
        raid = self.sb.gerenciador_io.raid
        return b"".join(raid.read_block(b) for b in inode.blocos)

    def test_texto_claro_some_do_disco(self):
        self.assertIn(b"mundo", self.conteudo_no_raid())
        self.executar("encrypt / segredo.txt MinhaChave123")
        self.assertNotIn(b"mundo", self.conteudo_no_raid())

    def test_cat_sem_chave_mostra_cifrado(self):
        self.executar("encrypt / segredo.txt MinhaChave123")
        saida = self.executar("cat / segredo.txt")
        self.assertIn("[CRIPTOGRAFADO]", saida)
        self.assertNotIn("mundo", saida)

    def test_cat_com_chave_correta(self):
        self.executar("encrypt / segredo.txt MinhaChave123")
        saida = self.executar("cat / segredo.txt MinhaChave123")
        self.assertIn("Olá mundo secreto", saida)

    def test_chave_errada_e_recusada(self):
        self.executar("encrypt / segredo.txt MinhaChave123")
        saida = self.executar("cat / segredo.txt ChaveErrada")
        self.assertIn("Chave incorreta", saida)
        self.assertNotIn("mundo", saida)

    def test_decrypt_restaura_o_texto(self):
        self.executar("encrypt / segredo.txt MinhaChave123")
        self.executar("decrypt / segredo.txt MinhaChave123")
        self.assertIn(b"mundo", self.conteudo_no_raid())
        self.assertIn("Olá mundo secreto", self.executar("cat / segredo.txt"))

    def test_echo_bloqueado_em_arquivo_cifrado(self):
        self.executar("encrypt / segredo.txt MinhaChave123")
        self.assertIn("criptografado", self.executar("echo / segredo.txt novo"))


if __name__ == "__main__":
    unittest.main(verbosity=2)