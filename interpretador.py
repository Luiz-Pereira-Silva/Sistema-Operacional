
import shlex
import numpy as np
import metodos_arquivos as file
import metodos_diretorios as dir
from gerenciador_io import GerenciadorIO

class Super_bloco:
    def __init__(self):
        self.bitmap_blocos = np.zeros(25, dtype=np.uint8)
        self.blocos = np.zeros((25, file.tamanho_bloco), dtype=np.uint8)
        self.bitmap_inodes = np.zeros(10, dtype=np.uint8)
        self.tabela_inodes = [None] * len(self.bitmap_inodes)
        self.root = dir.Diretorio("/")
        self.gerenciador_io = GerenciadorIO(self)

def interpretar_comando(comando, diretorio_atual, super_bloco):
    io = super_bloco.gerenciador_io

    try:
        partes = shlex.split(comando)
        if not partes:
            return diretorio_atual

        executar_string = partes[0]

        if executar_string == "mkdir":
            caminho, nome = partes[1], partes[2]
            alvo = procurar_diretorio(caminho, super_bloco.root)
            dir.criar_diretorio(alvo, nome)
            io.atualizar_metadados()

        elif executar_string == "touch":
            caminho, nome = partes[1], partes[2]
            alvo = procurar_diretorio(caminho, super_bloco.root)
            file.criar_arquivo(nome, alvo, super_bloco)
            io.atualizar_metadados()

        elif executar_string == "ls":
            alvo = procurar_diretorio(partes[1], super_bloco.root)
            io.ler_metadados()
            dir.listar_diretorio(alvo)

        elif executar_string == "echo":
            caminho, nome = partes[1], partes[2]
            string = " ".join(partes[3:])
            alvo = procurar_diretorio(caminho, super_bloco.root)
            inode = file.procurar_arquivo(nome, alvo, super_bloco)
            blocos_antigos = inode.blocos.copy()

            file.escrever_arquivo(nome, string, alvo, super_bloco)

            blocos_liberados = set(blocos_antigos) - set(inode.blocos)
            io.limpar_blocos(blocos_liberados)
            io.gravar_arquivo(inode)

        elif executar_string == "cat":
            caminho, nome = partes[1], partes[2]
            alvo = procurar_diretorio(caminho, super_bloco.root)
            inode = file.procurar_arquivo(nome, alvo, super_bloco)
            print(io.ler_arquivo(inode))

        elif executar_string == "rmdir":
            caminho, nome = partes[1], partes[2]
            alvo = procurar_diretorio(caminho, super_bloco.root)
            dir.remover_diretorio(alvo, nome)
            io.atualizar_metadados()

        elif executar_string == "rm":
            caminho, nome = partes[1], partes[2]
            alvo = procurar_diretorio(caminho, super_bloco.root)
            inode = file.procurar_arquivo(nome, alvo, super_bloco)
            blocos_antigos = inode.blocos.copy()

            file.remover_arquivo(nome, alvo, super_bloco)

            io.limpar_blocos(blocos_antigos)
            io.atualizar_metadados()

        elif executar_string == "cd":
            alvo = procurar_diretorio(partes[1], super_bloco.root)
            io.ler_metadados()
            return alvo

        else:
            print("Comando inexistente")

    except (ValueError, IndexError, IOError) as erro:
        print(f"Erro: {erro}")

    return diretorio_atual

def procurar_diretorio(caminho, diretorio_atual):
    if not caminho.startswith("/"):
        raise ValueError("O caminho deve ser absoluto")

    alvo = diretorio_atual
    if caminho == "/":
        return alvo

    for nome in caminho.split("/"):
        if not nome:
            continue

        encontrado = None

        for referencia in alvo.referencias:
            if isinstance(referencia, dir.Diretorio) and referencia.nome == nome:
                encontrado = referencia
                break

        if encontrado is None:
            raise ValueError("Diretório inexistente")

        alvo = encontrado

    return alvo
