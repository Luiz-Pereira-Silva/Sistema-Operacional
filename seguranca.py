import hashlib
import hmac
import os


class PermissaoNegada(Exception):
    pass


class Usuario:
    def __init__(self, nome, uid, gid, salt, hash_senha):
        self.nome = nome            # nome de login
        self.uid = uid              # identificador único do usuário
        self.gid = gid              # grupo primário
        self.salt = salt            # texto aleatório guardado em hex
        self.hash_senha = hash_senha    # resultado da hash da senha + salt


# criptografa a senha através de uma função de hash segura (PBKDF2 com SHA-256)
def gerar_hash(senha, salt_hex):
    return hashlib.pbkdf2_hmac(
        "sha256", senha.encode("utf-8"), bytes.fromhex(salt_hex), 100_000
    ).hex()


# cadastro no sistema 
class GerenciadorUsuarios:
    def __init__(self):
        self.usuarios = {}                       # achar usuário pelo nome
        self.grupos = {0: {"nome": "admin", "membros": {0}}}   # 
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
        """Conjunto de gids a que o usuário pertence (usaremos na ACL)."""
        return {gid for gid, g in self.grupos.items() if usuario.uid in g["membros"]}


class Sessao:
    def __init__(self, gerenciador):
        self.gerenciador = gerenciador
        self.usuario = gerenciador.usuarios["root"]   # sistema inicia como root

    @property
    def modo(self):
        return "MODO_KERNEL" if self.usuario.uid == 0 else "MODO_USUARIO"

    def exigir_kernel(self, operacao):
        if self.usuario.uid != 0:
            raise PermissaoNegada(
                f"'{operacao}' exige privilégios de superusuário (modo kernel)"
            )