import hashlib
import hmac
import os

LER, ESCREVER, EXECUTAR = 4, 2, 1
NOMES_ACAO = {LER: "LEITURA", ESCREVER: "ESCRITA", EXECUTAR: "EXECUÇÃO"}


class PermissaoNegada(Exception):
    pass


def formatar_permissoes(modo):
    letras = ""
    for deslocamento in (6, 3, 0):
        bits = (modo >> deslocamento) & 7
        letras += "r" if bits & LER else "-"
        letras += "w" if bits & ESCREVER else "-"
        letras += "x" if bits & EXECUTAR else "-"
    return letras


class Usuario:
    def __init__(self, nome, uid, gid, salt, hash_senha):
        self.nome = nome
        self.uid = uid
        self.gid = gid
        self.salt = salt
        self.hash_senha = hash_senha


def gerar_hash(senha, salt_hex):
    return hashlib.pbkdf2_hmac(
        "sha256", senha.encode("utf-8"), bytes.fromhex(salt_hex), 100_000
    ).hex()


class GerenciadorUsuarios:
    def __init__(self):
        self.usuarios = {}
        self.grupos = {0: {"nome": "admin", "membros": {0}}}
        self.proximo_uid = 1
        self.proximo_gid = 1
        self._registrar("root", "root", uid=0, gid=0)

    def _registrar(self, nome, senha, uid, gid):
        salt = os.urandom(16).hex()
        self.usuarios[nome] = Usuario(nome, uid, gid, salt, gerar_hash(senha, salt))

    def criar_grupo(self, nome):
        if any(g["nome"] == nome for g in self.grupos.values()):
            raise ValueError("Grupo já existe")
        self.grupos[self.proximo_gid] = {"nome": nome, "membros": set()}
        self.proximo_gid += 1

    def gid_por_nome(self, nome):
        for gid, g in self.grupos.items():
            if g["nome"] == nome:
                return gid
        raise ValueError("Grupo inexistente")

    def criar_usuario(self, nome, senha, nome_grupo):
        if nome in self.usuarios:
            raise ValueError("Usuário já existe")
        gid = self.gid_por_nome(nome_grupo)
        uid = self.proximo_uid
        self.proximo_uid += 1
        self._registrar(nome, senha, uid, gid)
        self.grupos[gid]["membros"].add(uid)

    def autenticar(self, nome, senha):
        usuario = self.usuarios.get(nome)
        if usuario is None:
            raise PermissaoNegada("Usuário ou senha inválidos")
        if not hmac.compare_digest(usuario.hash_senha, gerar_hash(senha, usuario.salt)):
            raise PermissaoNegada("Usuário ou senha inválidos")
        return usuario

    def grupos_do_usuario(self, usuario):
        return {gid for gid, g in self.grupos.items() if usuario.uid in g["membros"]}

    def nome_do_uid(self, uid):
        for u in self.usuarios.values():
            if u.uid == uid:
                return u.nome
        return str(uid)

    def nome_do_gid(self, gid):
        return self.grupos[gid]["nome"] if gid in self.grupos else str(gid)

    def uid_por_nome(self, nome):
        if nome not in self.usuarios:
            raise ValueError("Usuário inexistente")
        return self.usuarios[nome].uid


class Sessao:
    def __init__(self, gerenciador):
        self.gerenciador = gerenciador
        self.usuario = gerenciador.usuarios["root"]
        self.log = []

    @property
    def modo(self):
        return "MODO_KERNEL" if self.usuario.uid == 0 else "MODO_USUARIO"

    def exigir_kernel(self, operacao):
        if self.usuario.uid != 0:
            raise PermissaoNegada(
                f"'{operacao}' exige privilégios de superusuário (modo kernel)"
            )

    def verificar(self, objeto, acao, caminho):
        usuario = self.usuario
        if usuario.uid == 0:
            return

        if usuario.uid == objeto.dono_uid:
            bits = (objeto.permissoes >> 6) & 7
        elif objeto.grupo_gid in self.gerenciador.grupos_do_usuario(usuario):
            bits = (objeto.permissoes >> 3) & 7
        else:
            bits = objeto.permissoes & 7

        if bits & acao:
            return

        g = self.gerenciador
        print("[SISTEMA DE SEGURANÇA - VERIFICAÇÃO DE ACL]")
        print(f"Objeto      : {caminho}")
        print(f"Proprietário: {g.nome_do_uid(objeto.dono_uid)} (Grupo: {g.nome_do_gid(objeto.grupo_gid)})")
        print(f"Permissões  : {formatar_permissoes(objeto.permissoes)} ({objeto.permissoes:o})")
        print(f"Ação Pedida : {NOMES_ACAO[acao]} por '{usuario.nome}' "
              f"(Grupo: {g.nome_do_gid(usuario.gid)})")
        self.log.append(f"{usuario.nome} negado: {NOMES_ACAO[acao]} em {caminho}")
        raise PermissaoNegada(
            f"O usuário '{usuario.nome}' não possui permissão de "
            f"{NOMES_ACAO[acao].lower()} no objeto '{caminho}'.\n"
            "Tentativa não autorizada registrada nos logs do sistema."
        )

def exportar_seguranca(gerenciador):
    """Dados de usuários e grupos prontos para o JSON de metadados (sem senhas em texto puro)."""
    return {
        "usuarios": [
            {
                "nome": u.nome,
                "uid": u.uid,
                "gid": u.gid,
                "salt": u.salt,
                "hash_senha": u.hash_senha,
            }
            for u in gerenciador.usuarios.values()
        ],
        "grupos": [
            {"gid": gid, "nome": g["nome"], "membros": sorted(g["membros"])}
            for gid, g in gerenciador.grupos.items()
        ],
        "proximo_uid": gerenciador.proximo_uid,
        "proximo_gid": gerenciador.proximo_gid,
    }
