import hashlib
import hmac
import os

ITERACOES = 100_000


def derivar_chave(chave, salt):
    return hashlib.pbkdf2_hmac("sha256", chave.encode("utf-8"), salt, ITERACOES)


def _fluxo(chave_derivada, nonce, tamanho):
    saida = bytearray()
    contador = 0
    while len(saida) < tamanho:
        saida += hashlib.sha256(
            chave_derivada + nonce + contador.to_bytes(8, "big")
        ).digest()
        contador += 1
    return bytes(saida[:tamanho])


def _xor(dados, chave_derivada, nonce):
    fluxo = _fluxo(chave_derivada, nonce, len(dados))
    return bytes(a ^ b for a, b in zip(dados, fluxo))


def _verificador(chave_derivada):
    return hashlib.sha256(b"verificador" + chave_derivada).hexdigest()


def cifrar(dados, chave):
    """Devolve (ciphertext, salt_hex, nonce_hex, verificador_hex)."""
    salt = os.urandom(16)
    nonce = os.urandom(16)
    derivada = derivar_chave(chave, salt)
    return _xor(dados, derivada, nonce), salt.hex(), nonce.hex(), _verificador(derivada)


def decifrar(dados, chave, salt_hex, nonce_hex, verificador_hex):
    salt = bytes.fromhex(salt_hex)
    nonce = bytes.fromhex(nonce_hex)
    derivada = derivar_chave(chave, salt)
    if not hmac.compare_digest(_verificador(derivada), verificador_hex):
        raise ValueError("Chave incorreta")
    return _xor(dados, derivada, nonce)