"""Swap da memória virtual, gravado no RAID 5 via GerenciadorIO.

Fica num módulo próprio para que a etapa de memória não precise alterar o
gerenciador_io.py (que a etapa de segurança também altera). Cada página
ocupa 1 bloco do RAID, a partir de SWAP_BASE_LBA (longe dos metadados do FS),
com um registro "pid,pagina"; o acesso passa pela fila/escalonador de E/S.
"""

import metodos_arquivos as file

SWAP_BASE_LBA = 1000


class Swap:
    def __init__(self, io):
        self.io = io
        self.proximo = 0
        self.livres = []

    def alocar_slot(self):
        if self.livres:
            return self.livres.pop(0)
        slot = self.proximo
        self.proximo += 1
        return slot

    def liberar_slot(self, slot):
        if slot not in self.livres:
            self.livres.append(slot)
            self.livres.sort()

    def slots_em_uso(self):
        return self.proximo - len(self.livres)

    def gravar(self, slot, pid, pagina):
        registro = f"{pid},{pagina}".encode("utf-8").ljust(file.tamanho_bloco, b"\x00")
        self.io.solicitar_escrita(SWAP_BASE_LBA + slot, registro)
        self.io.processar_fila()

    def ler(self, slot, pid, pagina):
        self.io.solicitar_leitura(SWAP_BASE_LBA + slot)
        dados = self.io.processar_fila()[0]
        esperado = f"{pid},{pagina}".encode("utf-8")
        if dados.rstrip(b"\x00") != esperado:
            raise IOError(f"Swap corrompido no slot {slot}")
        return dados
