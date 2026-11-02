import metodos_arquivos as file
import metodos_diretorios as dir
import numpy as np

class Super_bloco:
    def __init__(self):
        self.bitmap_blocos = np.zeros(25, dtype=np.uint8)
        self.blocos = np.zeros((25, file.tamanho_bloco), dtype=np.uint8)
        self.bitmap_inodes = np.zeros(10, dtype=np.uint8)
        self.tabela_inodes = [None] * len(self.bitmap_inodes)
        self.root = dir.Diretorio("/")

def interpretar_comando(comando, diretorio_atual, super_bloco):
    j = 0
    executar_string = ""
    caminho = ""
    nome = ""
    string = ""
    passo = 0

    print()
    print(comando)

    for i in range(len(comando)):
        if comando[i] == " " and passo == 0:
            executar_string = comando[j:i]
            j = i + 1
            passo += 1

        elif comando[i] == " " and passo == 1:
            caminho = comando[j:i]
            j = i + 1
            passo += 1

        elif comando[i] == " " and passo == 2:
            nome = comando[j:i]
            j = i + 1
            passo += 1

        elif i == len(comando) - 1:
            if passo == 1:
                caminho = comando[j:i + 1]
            elif passo == 2:
                nome = comando[j:i + 1]
            elif passo == 3:
                string = comando[j:i + 1]

    diretorio_alvo = procurar_diretorio(
        caminho, diretorio_atual
    )

    match executar_string:

        case "mkdir":
            dir.criar_diretorio(diretorio_alvo, nome)

        case "touch":
            file.criar_arquivo(
                nome, diretorio_alvo, super_bloco
            )

        case "ls":
            dir.listar_diretorio(diretorio_alvo)

        case "echo":
            file.escrever_arquivo(
                nome, string, diretorio_alvo, super_bloco
            )

        case "cat":
            print(
                file.ler_arquivo(
                    nome, diretorio_alvo, super_bloco
                )
            )

        case "rmdir":
            dir.remover_diretorio(diretorio_alvo, nome)

        case "rm":
            file.remover_arquivo(
                nome, diretorio_alvo, super_bloco
            )

        case _:
            print("error")

def procurar_diretorio(caminho, diretorio_atual):
    assert caminho[0] == "/"
    diretorio_alvo = diretorio_atual
    if len(caminho) == 1:
        return diretorio_alvo
    nomes_diretorios = []
    j = 1
    for i in range (1, len(caminho)):
        if caminho[i] == "/" or i == len(caminho) - 1:
            nomes_diretorios.append(caminho[j: i+1])
            j = i+1
    for nome_diretorio in nomes_diretorios:
        encontrado = False
        for referencia in diretorio_alvo.referencias:
            if referencia.nome == nome_diretorio:
                diretorio_alvo = referencia
                encontrado = True
                break
        if not encontrado:
            raise ValueError("Diretório inexistente")
    return diretorio_alvo