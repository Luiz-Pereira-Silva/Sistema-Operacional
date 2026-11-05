import numpy as np

class Arquivo:
    def __init__(self, nome, inode_id):
        self.nome = nome
        self.inode_id = inode_id

    def __repr__(self):
        return f"(a, {self.nome})"


class Inode:
    def __init__(self, inode_id):
        self.inode_id = inode_id
        self.tamanho = 0
        self.blocos = []

    def __repr__(self):
        return (
            f"Inode(id={self.inode_id}, "
            f"tamanho={self.tamanho}, "
            f"blocos={self.blocos})"
        )

tamanho_bloco = 16

def alocar_novo_inode(super_bloco):
    for i in range(len(super_bloco.bitmap_inodes)):
        if super_bloco.bitmap_inodes[i] == 0:
            inode = Inode(i)
            super_bloco.bitmap_inodes[i] = 1
            super_bloco.tabela_inodes[i] = inode
            return inode
    raise ValueError("Não existem inodes disponíveis")

def desalocar_inode(inode_id, super_bloco):
    inode = super_bloco.tabela_inodes[inode_id]
    if inode is None:
        raise ValueError("Inode inexistente")
    for bloco in inode.blocos:
        super_bloco.bitmap_blocos[bloco] = 0
        super_bloco.blocos[bloco] = 0
    super_bloco.bitmap_inodes[inode_id] = 0
    super_bloco.tabela_inodes[inode_id] = None

def alocar_inode(string, super_bloco):
    dados = string.encode("utf-8")
    numero_de_blocos = (len(dados) + tamanho_bloco - 1) // tamanho_bloco
    blocos = []
    if numero_de_blocos == 0:
        return blocos
    for i in range(len(super_bloco.bitmap_blocos)):
        if super_bloco.bitmap_blocos[i] == 0:
            blocos.append(i)
            super_bloco.bitmap_blocos[i] = 1
            if len(blocos) == numero_de_blocos:
                break
    if len(blocos) < numero_de_blocos:
        for bloco in blocos:
            super_bloco.bitmap_blocos[bloco] = 0
        raise ValueError("Espaço insuficiente no disco")
    for j in range(len(dados)):
        indice_bloco = j // tamanho_bloco
        posicao = j % tamanho_bloco
        super_bloco.blocos[blocos[indice_bloco]][posicao] = dados[j]
    return blocos

def criar_arquivo(nome, diretorio_atual, super_bloco):
    for referencia in diretorio_atual.referencias:
        if referencia.nome == nome:
            raise ValueError("Arquivo já existe")
    inode = alocar_novo_inode(super_bloco)
    diretorio_atual.referencias.append(Arquivo(nome, inode.inode_id))

def procurar_arquivo(nome, diretorio_atual, super_bloco):
    for referencia in diretorio_atual.referencias:
        if isinstance(referencia, Arquivo):
            if referencia.nome == nome:
                return super_bloco.tabela_inodes[referencia.inode_id]
    raise ValueError("Arquivo inexistente")

def escrever_arquivo(nome, string, diretorio_atual, super_bloco):
    inode = procurar_arquivo(nome, diretorio_atual, super_bloco)
    blocos_antigos = inode.blocos.copy()
    for bloco in blocos_antigos:
        super_bloco.bitmap_blocos[bloco] = 0
    try:
        novos_blocos = alocar_inode(string, super_bloco)
    except ValueError:
        for bloco in blocos_antigos:
            super_bloco.bitmap_blocos[bloco] = 1
        raise
    for bloco in blocos_antigos:
        if bloco not in novos_blocos:
            super_bloco.blocos[bloco] = 0
    inode.blocos = novos_blocos
    inode.tamanho = len(string.encode("utf-8"))

def remover_arquivo(nome, diretorio_atual, super_bloco):
    for referencia in diretorio_atual.referencias:
        if isinstance(referencia, Arquivo):
            if referencia.nome == nome:
                desalocar_inode(
                    referencia.inode_id,
                    super_bloco
                )
                diretorio_atual.referencias.remove(referencia)
                return
    raise ValueError("Arquivo inexistente")

def ler_arquivo(nome, diretorio_atual, super_bloco):
    inode = procurar_arquivo(nome, diretorio_atual, super_bloco)
    dados = bytearray()
    for bloco in inode.blocos:
        dados.extend(super_bloco.blocos[bloco])
    return bytes(dados[:inode.tamanho]).decode("utf-8")