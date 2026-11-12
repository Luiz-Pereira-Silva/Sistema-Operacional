class Diretorio():
    def __init__ (self, nome, dono_uid=0, grupo_gid=0, permissoes=0o755):
        self.nome = nome
        self.referencias = []
        self.dono_uid = dono_uid
        self.grupo_gid = grupo_gid
        self.permissoes = permissoes
    def __str__(self):
        return f"{self.nome}"
    def __repr__(self):
        return f"(d, {self.nome})"

def criar_diretorio(diretorio_atual, nome, dono_uid=0, grupo_gid=0):
    diretorio_atual.referencias.append(Diretorio(nome, dono_uid, grupo_gid))
    print("diretorio adicionado com sucesso")

def remover_diretorio(diretorio_atual, nome):
    sucesso = 0
    for diretorio in diretorio_atual.referencias:
        if diretorio.nome == nome:
            diretorio_atual.referencias.remove(diretorio)
            print("removido com sucesso")
            sucesso += 1
    if not sucesso:
        print("diretorio não existe")

def listar_diretorio(diretorio_atual):
    print(f"{diretorio_atual.nome}: {diretorio_atual.referencias}")