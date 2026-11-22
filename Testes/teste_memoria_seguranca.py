"""Integração memória x segurança.

Parte 1 usa uma sessão simulada (stub) e roda mesmo sem a etapa de segurança.
Parte 2 usa a segurança de verdade e só roda quando seguranca.py existir (main).
"""
import importlib.util
import unittest
from contextlib import redirect_stdout
from io import StringIO

from interpretador import Super_bloco, interpretar_comando

TEM_SEGURANCA = importlib.util.find_spec("seguranca") is not None


class NegadoStub(Exception):
    pass


class Usuario:
    def __init__(self, nome, uid):
        self.nome, self.uid = nome, uid


class SessaoStub:
    """Imita a interface usada pela memória: usuario, log e exigir_kernel."""
    def __init__(self):
        self.usuario = Usuario("root", 0)
        self.log = []

    def exigir_kernel(self, operacao):
        if self.usuario.uid != 0:
            raise NegadoStub(f"'{operacao}' exige privilégios de superusuário")


class TesteMemoriaComSessaoStub(unittest.TestCase):
    def setUp(self):
        self.sb = Super_bloco()
        self.sb.sessao = SessaoStub()          # ganha sessão sem tocar na segurança real
        self.atual = self.sb.root

    def cmd(self, comando):
        with redirect_stdout(StringIO()) as saida:
            try:
                interpretar_comando(comando, self.atual, self.sb)
            except NegadoStub as erro:
                return f"NEGADO {erro}"
        return saida.getvalue()

    def entrar_como(self, nome, uid):
        self.sb.sessao.usuario = Usuario(nome, uid)

    def test_root_cria_processo_critico(self):
        self.cmd("create_process --name K --size 512KB --type critical")
        self.assertIn("K", [p.nome for p in self.sb.processos.values()])

    def test_usuario_nao_cria_processo_critico_e_fica_no_log(self):
        self.entrar_como("carlos", 1)
        saida = self.cmd("create_process --name K --size 512KB --type critical")
        self.assertIn("NEGADO", saida)
        self.assertEqual(self.sb.processos, {})
        self.assertTrue(any("carlos negado" in r for r in self.sb.sessao.log))

    def test_usuario_cria_processo_normal_e_vira_dono(self):
        self.entrar_como("carlos", 1)
        self.cmd("create_process --name App --size 10KB --type normal")
        self.assertEqual(next(iter(self.sb.processos.values())).dono_uid, 1)

    def test_usuario_nao_mexe_em_processo_de_outro(self):
        self.entrar_como("carlos", 1)
        self.cmd("create_process --name App --size 10KB --type normal")
        self.entrar_como("ana", 2)
        self.assertIn("NEGADO", self.cmd("terminate_process --name App"))
        self.assertIn("NEGADO", self.cmd("execute_step --process App --instruction 'LOAD Página 0'"))
        self.assertEqual(len(self.sb.processos), 1)
        self.entrar_como("root", 0)
        self.cmd("terminate_process --name App")
        self.assertEqual(self.sb.processos, {})

    def test_compactar_e_trocar_algoritmo_exigem_kernel(self):
        self.entrar_como("carlos", 1)
        self.assertIn("NEGADO", self.cmd("memory_compact"))
        self.assertIn("NEGADO", self.cmd("set_replacement --algo fifo"))

    def test_status_e_livre_para_usuario(self):
        self.entrar_como("carlos", 1)
        self.assertIn("MAPA DA ÁREA", self.cmd("memory_status --reserved"))

    def test_comando_negado_nao_conta_para_relatorio_periodico(self):
        self.entrar_como("carlos", 1)
        antes = self.sb.memoria.comandos
        self.cmd("memory_compact")
        self.assertEqual(self.sb.memoria.comandos, antes)


@unittest.skipUnless(TEM_SEGURANCA, "etapa de segurança ainda não está na main")
class TesteMemoriaComSegurancaReal(unittest.TestCase):
    def setUp(self):
        self.sb = Super_bloco(num_molduras=1)      # 1 moldura força troca de página
        self.atual = self.sb.root
        self.cmd("groupadd devs")
        self.cmd("useradd carlos devs senha123")

    def cmd(self, comando):
        with redirect_stdout(StringIO()) as saida:
            interpretar_comando(comando, self.atual, self.sb)
        return saida.getvalue()

    def test_usuario_comum_negado_em_area_critica(self):
        self.cmd("login carlos senha123")
        saida = self.cmd("create_process --name K --size 512KB --type critical")
        self.assertIn("[NEGADO]", saida)
        self.assertEqual(self.sb.processos, {})
        self.cmd("login root root")
        self.assertIn("carlos negado", self.cmd("logs"))

    def test_antivirus_continua_ok_com_swap_no_raid(self):
        self.cmd("create_process --name A --size 8KB --type normal")
        self.cmd("set_replacement --algo lru")
        for pagina in (0, 1, 0, 1):
            self.cmd(f"translate_address --process A --page {pagina}")
        self.assertNotIn("[ALERTA]", self.cmd("antivirus_scan /"))


if __name__ == "__main__":
    unittest.main()
