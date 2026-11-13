import hashlib
import json
from disk_simulator import (
    RAID5,
    FCFSScheduler,
    IORequest
)
import metodos_arquivos as file

class GerenciadorIO:

    def __init__(self, super_bloco):
        self.super_bloco = super_bloco
        self.raid = RAID5(disk_count=3,block_size=file.tamanho_bloco)
        self.scheduler = FCFSScheduler()
        self.cabeca = 0
        self.fila = []
        self.metadata_blocks = 0

    def solicitar_escrita(self, bloco, dados):
        self.fila.append((
            IORequest(
                track=bloco,
                operation="WRITE",
                description=f"Gravação do bloco {bloco}"
            ),
            "WRITE",
            bloco,
            bytes(dados)
        ))

    def solicitar_leitura(self, bloco):
        self.fila.append((
            IORequest(
                track=bloco,
                operation="READ",
                description=f"Leitura do bloco {bloco}"
            ),"READ", bloco, None))

    def processar_fila(self):
        if not self.fila:
            return []
        requisicoes = [item[0] for item in self.fila]
        resultado = self.scheduler.schedule(requisicoes, self.cabeca)
        print("\n========== ESCALONAMENTO FCFS ==========")
        print("Ordem de atendimento:", " -> ".join(map(str, resultado.order)))
        print("Deslocamentos:",resultado.movements)
        print("Movimento total:", resultado.total_movement, "trilhas")
        resultados_leitura = []
        for requisicao, operacao, bloco, dados in self.fila:
            if operacao == "WRITE":
                self.raid.write_block(bloco,dados)
                print(f"[DISCO] WRITE - Bloco lógico {bloco}")
            elif operacao == "READ":
                dados_lidos = self.raid.read_block(bloco)
                resultados_leitura.append(dados_lidos)
                print(f"[DISCO] READ - Bloco lógico {bloco}")
        self.cabeca = resultado.order[-1]
        self.fila.clear()
        print("========================================\n")
        return resultados_leitura

    def gravar_bloco_fs(self, bloco):
        dados = self.super_bloco.blocos[bloco].tobytes()
        self.solicitar_escrita(bloco, dados)

    def persistir_metadados(self):
        def serializar_diretorio(diretorio):
            referencias = []
            for referencia in diretorio.referencias:
                if isinstance(referencia, file.Arquivo):
                    referencias.append({
                        "tipo": "arquivo",
                        "nome": referencia.nome,
                        "inode_id": referencia.inode_id
                    })
                else:
                    referencias.append({
                        "tipo": "diretorio",
                        "dados": serializar_diretorio(referencia)
                    })
            return {
                "nome": diretorio.nome,
                "dono_uid": diretorio.dono_uid,
                "grupo_gid": diretorio.grupo_gid,
                "permissoes": diretorio.permissoes,
                "referencias": referencias
            }
        inodes = []
        for inode in self.super_bloco.tabela_inodes:
            if inode is None:
                inodes.append(None)
            else:
                inodes.append({
                    "inode_id": inode.inode_id,
                    "tamanho": inode.tamanho,
                    "blocos": inode.blocos,
                    "dono_uid": inode.dono_uid,
                    "grupo_gid": inode.grupo_gid,
                    "permissoes": inode.permissoes,
                    "criptografado": inode.criptografado,
                    "salt_cripto": inode.salt_cripto,
                    "nonce_cripto": inode.nonce_cripto,
                    "verificador_chave": inode.verificador_chave,
                    "hashes_blocos": inode.hashes_blocos
                })
        metadados = {
            "bitmap_blocos": self.super_bloco.bitmap_blocos.tolist(),
            "bitmap_inodes": self.super_bloco.bitmap_inodes.tolist(),
            "inodes": inodes,
            "root": serializar_diretorio(self.super_bloco.root)
        }
        dados = json.dumps(metadados).encode("utf-8")
        tamanho_bloco = file.tamanho_bloco
        quantidade = (len(dados) + tamanho_bloco - 1) // tamanho_bloco

        for i in range(max(quantidade, self.metadata_blocks)):
            inicio = i * tamanho_bloco
            bloco = dados[inicio:inicio + tamanho_bloco]
            bloco = bloco.ljust(tamanho_bloco, b"\x00")
            lba = 25 + i
            self.solicitar_escrita(lba, bloco)
        self.metadata_blocks = quantidade

    def ler_metadados(self):
        for i in range(self.metadata_blocks):
            self.solicitar_leitura(25 + i)
        if self.metadata_blocks:
            return self.processar_fila()
        return []

    def gravar_arquivo(self, inode):
        # registro oficial de integridade: hash de cada bloco no momento da gravação
        inode.hashes_blocos = [
            hashlib.sha256(self.super_bloco.blocos[bloco].tobytes()).hexdigest()
            for bloco in inode.blocos
        ]
        for bloco in inode.blocos:
            self.gravar_bloco_fs(bloco)
        self.persistir_metadados()
        self.processar_fila()

    def ler_arquivo(self, inode):
        for bloco in inode.blocos:
            self.solicitar_leitura(bloco)
        dados_lidos = self.processar_fila()
        dados = bytearray()
        for bloco in dados_lidos:
            dados.extend(bloco)
        return bytes(dados[:inode.tamanho]).decode("utf-8")

    def limpar_blocos(self, blocos):
        zeros = bytes(file.tamanho_bloco)
        for bloco in blocos:
            self.solicitar_escrita(bloco, zeros)

    def atualizar_metadados(self):
        self.persistir_metadados()
        self.processar_fila()

    def ler_arquivo_bytes(self, inode):
        for bloco in inode.blocos:
            self.solicitar_leitura(bloco)
        dados_lidos = self.processar_fila()
        dados = bytearray()
        for bloco in dados_lidos:
            dados.extend(bloco)
        return bytes(dados[:inode.tamanho])
