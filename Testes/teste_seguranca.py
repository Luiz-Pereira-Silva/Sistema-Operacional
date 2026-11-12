import unittest
from contextlib import redirect_stdout
from io import StringIO
from interpretador import Super_bloco, interpretar_comando


class Base(unittest.TestCase):
    def setUp(self):
        self.sb = Super_bloco()
        self.atual = self.sb.root
        self.executar("groupadd devs")
        self.executar("useradd carlos devs abc123")

    def executar(self, comando):
        with redirect_stdout(StringIO()) as saida:
            self.atual = interpretar_comando(comando, self.atual, self.sb)
        return saida.getvalue()


class TestUsuarios(Base):
    def test_senha_nao_fica_em_texto_puro(self):
        u = self.sb.usuarios.usuarios["carlos"]
        self.assertNotIn("abc123", u.hash_senha)
        self.assertEqual(len(u.salt), 32)

    def test_login_correto_e_errado(self):
        self.assertIn("[NEGADO]", self.executar("login carlos errada"))
        self.assertIn("MODO_USUARIO", self.executar("login carlos abc123"))

    def test_usuario_comum_nao_cria_usuario(self):
        self.executar("login carlos abc123")
        self.assertIn("[NEGADO]", self.executar("useradd ana devs 123"))


class TestACL(Base):
    def test_outros_sem_permissao_sao_negados(self):
        self.executar("touch / segredo.txt")
        self.executar("echo / segredo.txt conteudo")
        self.executar("chmod / segredo.txt 750")
        self.executar("login carlos abc123")
        self.assertIn("[NEGADO]", self.executar("cat / segredo.txt"))

    def test_grupo_le_mas_nao_escreve(self):
        self.executar("touch / g.txt")
        self.executar("echo / g.txt oi")
        self.executar("chown / g.txt root devs")
        self.executar("chmod / g.txt 640")
        self.executar("login carlos abc123")
        self.assertIn("oi", self.executar("cat / g.txt"))
        self.assertIn("[NEGADO]", self.executar("echo / g.txt x"))

    def test_dono_em_diretorio_liberado(self):
        self.executar("mkdir / pub")
        self.executar("chmod / pub 777")
        self.executar("login carlos abc123")
        self.executar("touch /pub a.txt")
        self.executar("echo /pub a.txt oi")
        self.assertIn("oi", self.executar("cat /pub a.txt"))

    def test_so_dono_ou_root_muda_permissao(self):
        self.executar("touch / r.txt")
        self.executar("login carlos abc123")
        self.assertIn("[NEGADO]", self.executar("chmod / r.txt 777"))

    def test_chown_exige_kernel(self):
        self.executar("touch / r.txt")
        self.executar("login carlos abc123")
        self.assertIn("[NEGADO]", self.executar("chown / r.txt carlos"))

    def test_negacao_vai_para_o_log(self):
        self.executar("touch / r.txt")
        self.executar("chmod / r.txt 700")
        self.executar("login carlos abc123")
        self.executar("cat / r.txt")
        self.assertEqual(len(self.sb.sessao.log), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)