import getpass
import shlex
import antivirus
import numpy as np
import metodos_arquivos as file
import metodos_diretorios as dir
from gerenciador_io import GerenciadorIO
from seguranca import (
    GerenciadorUsuarios, Sessao, PermissaoNegada,
    LER, ESCREVER, EXECUTAR, formatar_permissoes
)

class Super_bloco:
    def __init__(self):
        self.bitmap_blocos = np.zeros(25, dtype=np.uint8)
        self.blocos = np.zeros((25, file.tamanho_bloco), dtype=np.uint8)
        self.bitmap_inodes = np.zeros(10, dtype=np.uint8)
        self.tabela_inodes = [None] * len(self.bitmap_inodes)
        self.root = dir.Diretorio("/")
        self.usuarios = GerenciadorUsuarios()
        self.sessao = Sessao(self.usuarios)
        self.gerenciador_io = GerenciadorIO(self)

def caminho_completo(caminho, nome):
    return caminho.rstrip("/") + "/" + nome

def procurar_objeto(alvo, nome, super_bloco):
    for ref in alvo.referencias:
        if ref.nome == nome:
            if isinstance(ref, file.Arquivo):
                return super_bloco.tabela_inodes[ref.inode_id]
            return ref
    raise ValueError("Objeto inexistente")

def interpretar_comando(comando, diretorio_atual, super_bloco):
    io = super_bloco.gerenciador_io
    sessao = super_bloco.sessao

    try:
        partes = shlex.split(comando)
        if not partes:
            return diretorio_atual

        executar_string = partes[0]

        if executar_string == "mkdir":
            caminho, nome = partes[1], partes[2]
            alvo = procurar_diretorio(caminho, super_bloco.root, sessao)
            sessao.verificar(alvo, ESCREVER, caminho)
            dir.criar_diretorio(alvo, nome, sessao.usuario.uid, sessao.usuario.gid)
            io.atualizar_metadados()

        elif executar_string == "touch":
            caminho, nome = partes[1], partes[2]
            alvo = procurar_diretorio(caminho, super_bloco.root, sessao)
            sessao.verificar(alvo, ESCREVER, caminho)
            file.criar_arquivo(nome, alvo, super_bloco)
            io.atualizar_metadados()

        elif executar_string == "ls":
            alvo = procurar_diretorio(partes[1], super_bloco.root, sessao)
            sessao.verificar(alvo, LER, partes[1])
            io.ler_metadados()
            dir.listar_diretorio(alvo)

        elif executar_string == "echo":
            caminho, nome = partes[1], partes[2]
            string = " ".join(partes[3:])
            alvo = procurar_diretorio(caminho, super_bloco.root, sessao)
            inode = file.procurar_arquivo(nome, alvo, super_bloco)
            sessao.verificar(inode, ESCREVER, caminho_completo(caminho, nome))
            blocos_antigos = inode.blocos.copy()

            file.escrever_arquivo(nome, string, alvo, super_bloco)

            blocos_liberados = set(blocos_antigos) - set(inode.blocos)
            io.limpar_blocos(blocos_liberados)
            io.gravar_arquivo(inode)

        elif executar_string == "cat":
            caminho, nome = partes[1], partes[2]
            alvo = procurar_diretorio(caminho, super_bloco.root, sessao)
            inode = file.procurar_arquivo(nome, alvo, super_bloco)
            sessao.verificar(inode, LER, caminho_completo(caminho, nome))
            print(io.ler_arquivo(inode))

        elif executar_string == "rmdir":
            caminho, nome = partes[1], partes[2]
            alvo = procurar_diretorio(caminho, super_bloco.root, sessao)
            sessao.verificar(alvo, ESCREVER, caminho)
            dir.remover_diretorio(alvo, nome)
            io.atualizar_metadados()

        elif executar_string == "rm":
            caminho, nome = partes[1], partes[2]
            alvo = procurar_diretorio(caminho, super_bloco.root, sessao)
            sessao.verificar(alvo, ESCREVER, caminho)
            inode = file.procurar_arquivo(nome, alvo, super_bloco)
            blocos_antigos = inode.blocos.copy()

            file.remover_arquivo(nome, alvo, super_bloco)

            io.limpar_blocos(blocos_antigos)
            io.atualizar_metadados()

        elif executar_string == "cd":
            alvo = procurar_diretorio(partes[1], super_bloco.root, sessao)
            io.ler_metadados()
            return alvo

        # ---------- comandos novos (etapa 3) ----------
        elif executar_string == "login":
            senha = partes[2] if len(partes) > 2 else getpass.getpass("Senha: ")
            usuario = super_bloco.usuarios.autenticar(partes[1], senha)
            sessao.usuario = usuario
            grupo = super_bloco.usuarios.nome_do_gid(usuario.gid)
            print(f"Autenticado com sucesso. Usuário: '{usuario.nome}' | "
                  f"Grupo: '{grupo}' | Modo: {sessao.modo}")

        elif executar_string == "whoami":
            print(f"{sessao.usuario.nome} ({sessao.modo})")

        elif executar_string == "groupadd":
            sessao.exigir_kernel("groupadd")
            super_bloco.usuarios.criar_grupo(partes[1])
            io.atualizar_metadados()
            print("Grupo criado com sucesso")

        elif executar_string == "useradd":
            sessao.exigir_kernel("useradd")
            nome, grupo = partes[1], partes[2]
            senha = partes[3] if len(partes) > 3 else getpass.getpass("Senha: ")
            super_bloco.usuarios.criar_usuario(nome, senha, grupo)
            io.atualizar_metadados()
            print("Usuário criado com sucesso")

        elif executar_string == "chmod":
            caminho, nome, modo = partes[1], partes[2], partes[3]
            alvo = procurar_diretorio(caminho, super_bloco.root, sessao)
            objeto = procurar_objeto(alvo, nome, super_bloco)
            if sessao.usuario.uid not in (0, objeto.dono_uid):
                raise PermissaoNegada("apenas o proprietário ou o root pode alterar permissões")
            novo = int(modo, 8)
            if not 0 <= novo <= 0o777:
                raise ValueError("Modo inválido (use 3 dígitos octais, ex.: 750)")
            objeto.permissoes = novo
            io.atualizar_metadados()

        elif executar_string == "chown":
            sessao.exigir_kernel("chown")
            caminho, nome, dono = partes[1], partes[2], partes[3]
            alvo = procurar_diretorio(caminho, super_bloco.root, sessao)
            objeto = procurar_objeto(alvo, nome, super_bloco)
            objeto.dono_uid = super_bloco.usuarios.uid_por_nome(dono)
            if len(partes) > 4:
                objeto.grupo_gid = super_bloco.usuarios.gid_por_nome(partes[4])
            io.atualizar_metadados()

        elif executar_string == "stat":
            caminho, nome = partes[1], partes[2]
            alvo = procurar_diretorio(caminho, super_bloco.root, sessao)
            objeto = procurar_objeto(alvo, nome, super_bloco)
            u = super_bloco.usuarios
            print(f"Proprietário: {u.nome_do_uid(objeto.dono_uid)} (Grupo: {u.nome_do_gid(objeto.grupo_gid)})")
            print(f"Permissões  : {formatar_permissoes(objeto.permissoes)} ({objeto.permissoes:o})")


        elif executar_string == "antivirus_scan":
            sessao.exigir_kernel("antivirus_scan")
            alvo = procurar_diretorio(partes[1], super_bloco.root, sessao)
            antivirus.varrer(super_bloco, alvo, partes[1])

        elif executar_string == "simular_ataque":
            sessao.exigir_kernel("simular_ataque")
            caminho, nome = partes[1], partes[2]
            alvo = procurar_diretorio(caminho, super_bloco.root, sessao)
            inode = file.procurar_arquivo(nome, alvo, super_bloco)
            bloco, disco, stripe = antivirus.simular_adulteracao(super_bloco, inode)
            print(f"[SIMULAÇÃO] Bloco lógico {bloco} adulterado diretamente no "
                  f"Disco {disco} (stripe {stripe}), sem passar pelo sistema de arquivos.")

        elif executar_string == "logs":
            sessao.exigir_kernel("logs")
            if sessao.log:
                for registro in sessao.log:
                    print(registro)
            else:
                print("(sem registros)")

        else:
            print("Comando inexistente")

    except PermissaoNegada as erro:
        print(f"[NEGADO]: {erro}")
    except (ValueError, IndexError, IOError) as erro:
        print(f"Erro: {erro}")

    return diretorio_atual

def procurar_diretorio(caminho, diretorio_atual, sessao=None):
    if not caminho.startswith("/"):
        raise ValueError("O caminho deve ser absoluto")

    alvo = diretorio_atual
    if sessao:
        sessao.verificar(alvo, EXECUTAR, "/")
    if caminho == "/":
        return alvo

    percorrido = ""
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
        percorrido += "/" + nome
        if sessao:
            sessao.verificar(alvo, EXECUTAR, percorrido)

    return alvo
