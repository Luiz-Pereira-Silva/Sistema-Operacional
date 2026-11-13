import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from interpretador import Super_bloco, interpretar_comando


class TestPersistenciaUsuarios(unittest.TestCase):
    def setUp(self):
        self.sb = Super_bloco()
        self.atual = self.sb.root
        self.executar("groupadd devs")
        self.executar("useradd carlos devs senhaSecreta99")

    def executar(self, comando):
        with redirect_stdout(StringIO()) as saida:
            self.atual = interpretar_comando(comando, self.atual, self.sb)
        return saida.getvalue()

    def metadados_do_disco(self):
        io = self.sb.gerenciador_io
        with redirect_stdout(StringIO()):
            blocos = io.ler_metadados()
        return b"".join(blocos).rstrip(b"\x00")

    def test_usuarios_e_grupos_vao_para_o_disco(self):
        meta = json.loads(self.metadados_do_disco())
        nomes = [u["nome"] for u in meta["seguranca"]["usuarios"]]
        self.assertIn("carlos", nomes)
        self.assertIn("root", nomes)
        grupos = [g["nome"] for g in meta["seguranca"]["grupos"]]
        self.assertIn("devs", grupos)

    def test_senha_em_texto_puro_nunca_vai_para_o_disco(self):
        bruto = self.metadados_do_disco()
        self.assertNotIn(b"senhaSecreta99", bruto)
        self.assertIn(b"hash_senha", bruto)


if __name__ == "__main__":
    unittest.main(verbosity=2)
