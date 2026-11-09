
import unittest
from contextlib import redirect_stdout
from io import StringIO
from interpretador import Super_bloco, interpretar_comando, procurar_diretorio
import metodos_arquivos as file
import metodos_diretorios as dir

class TestInterpretador(unittest.TestCase):
    def setUp(self):
        self.sb = Super_bloco()
        self.atual = self.sb.root

    def executar(self, comando):
        with redirect_stdout(StringIO()) as saida:
            self.atual = interpretar_comando(comando, self.atual, self.sb)
        if saida.getvalue().strip():
            print(saida.getvalue().strip())

    def verificar(self, descricao, resultado):
        print(f"{descricao}: {'OK' if resultado else 'FALHOU'}")
        self.assertTrue(resultado)

    def test_super_bloco(self):
        print("\n========== TESTE SUPER BLOCO ==========")
        self.verificar("Bitmap de blocos", len(self.sb.bitmap_blocos) == 25)
        self.verificar("Bitmap de inodes", len(self.sb.bitmap_inodes) == 10)
        self.verificar("Diretório raiz", isinstance(self.sb.root, dir.Diretorio))

    def test_procurar_diretorio_raiz(self):
        print("\n========== TESTE DIRETÓRIO RAIZ ==========")
        resultado = procurar_diretorio("/", self.sb.root)
        self.verificar("Localização da raiz", resultado is self.sb.root)

    def test_criar_diretorio(self):
        print("\n========== TESTE MKDIR ==========")
        self.executar("mkdir / pasta")
        self.verificar("Criação do diretório", len(self.sb.root.referencias) == 1)
        self.verificar("Nome do diretório", self.sb.root.referencias[0].nome == "pasta")

    def test_criar_arquivo(self):
        print("\n========== TESTE TOUCH ==========")
        self.executar("touch / teste.txt")
        self.verificar("Criação do arquivo", len(self.sb.root.referencias) == 1)
        self.verificar("Referência do tipo Arquivo", isinstance(self.sb.root.referencias[0], file.Arquivo))

    def test_escrever_e_ler_arquivo(self):
        print("\n========== TESTE ECHO E CAT ==========")
        self.executar("touch / teste.txt")
        self.executar("echo / teste.txt Olá mundo")

        with redirect_stdout(StringIO()) as saida:
            interpretar_comando("cat / teste.txt", self.atual, self.sb)

        conteudo = saida.getvalue().strip().splitlines()[-1]
        print("Conteúdo recuperado:", conteudo)
        self.verificar("Integridade do conteúdo", conteudo == "Olá mundo")

    def test_remover_arquivo(self):
        print("\n========== TESTE RM ==========")
        self.executar("touch / teste.txt")
        self.executar("rm / teste.txt")
        self.verificar("Remoção da referência", len(self.sb.root.referencias) == 0)
        self.verificar("Liberação do inode", self.sb.bitmap_inodes[0] == 0)

    def test_cd(self):
        print("\n========== TESTE CD ==========")
        self.executar("mkdir / pasta")
        self.executar("cd /pasta")
        self.verificar("Navegação para pasta", self.atual.nome == "pasta")

    def test_ls(self):
        print("\n========== TESTE LS ==========")
        self.executar("mkdir / pasta")

        with redirect_stdout(StringIO()) as saida:
            interpretar_comando("ls /", self.atual, self.sb)

        resultado = saida.getvalue()
        print("Resultado da listagem:")
        print(resultado.strip())
        self.verificar("Listagem do diretório", "pasta" in resultado)

    def test_rmdir(self):
        print("\n========== TESTE RMDIR ==========")
        self.executar("mkdir / pasta")
        self.executar("rmdir / pasta")
        self.verificar("Remoção do diretório", len(self.sb.root.referencias) == 0)

    def test_caminho_aninhado(self):
        print("\n========== TESTE CAMINHO ANINHADO ==========")
        self.executar("mkdir / pasta")
        self.executar("mkdir /pasta subpasta")
        alvo = procurar_diretorio("/pasta/subpasta", self.sb.root)
        self.verificar("Localização do subdiretório", alvo.nome == "subpasta")

if __name__ == "__main__":
    unittest.main(verbosity=2)
