import unittest
from contextlib import redirect_stdout
from io import StringIO
from interpretador import Super_bloco, interpretar_comando


class TestAntivirus(unittest.TestCase):
    def setUp(self):
        self.sb = Super_bloco()
        self.atual = self.sb.root
        self.executar("touch / limpo.txt")
        self.executar("echo / limpo.txt arquivo normal")

    def executar(self, comando):
        with redirect_stdout(StringIO()) as saida:
            self.atual = interpretar_comando(comando, self.atual, self.sb)
        return saida.getvalue()

    def test_varredura_sem_problemas(self):
        saida = self.executar("antivirus_scan /")
        self.assertIn("[OK - Íntegro]", saida)
        self.assertNotIn("[ALERTA]", saida)

    def test_escrita_legitima_atualiza_o_registro(self):
        self.executar("echo / limpo.txt novo conteudo bem maior que o anterior, ocupando varios blocos")
        saida = self.executar("antivirus_scan /")
        self.assertNotIn("[ALERTA]", saida)

    def test_detecta_adulteracao_direta_no_disco(self):
        self.executar("simular_ataque / limpo.txt")
        saida = self.executar("antivirus_scan /")
        self.assertIn("difere do registro oficial", saida)
        self.assertIn("modificação direta", saida)
        self.assertIn("Paridade RAID inconsistente", saida)

    def test_detecta_assinatura_maliciosa(self):
        self.executar("touch / infectado.txt")
        self.executar("echo / infectado.txt abc MALWARE_SIG xyz")
        saida = self.executar("antivirus_scan /")
        self.assertIn("Assinatura maliciosa", saida)

    def test_arquivo_criptografado_integro(self):
        self.executar("encrypt / limpo.txt Chave123")
        saida = self.executar("antivirus_scan /")
        self.assertIn("Criptografado e Íntegro", saida)

    def test_usuario_comum_nao_executa_varredura(self):
        self.executar("groupadd devs")
        self.executar("useradd carlos devs abc123")
        self.executar("login carlos abc123")
        self.assertIn("[NEGADO]", self.executar("antivirus_scan /"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
