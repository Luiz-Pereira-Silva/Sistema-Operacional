import numpy as np
import metodos_diretorios as dir
from leitura_de_comandos import interpretar_comando, Super_bloco
import metodos_arquivos as file

super_bloco = Super_bloco()
diretorio_atual = super_bloco.root

while(1):
    diretorio_atual = interpretar_comando(input(f"{diretorio_atual}: "), diretorio_atual, super_bloco)

# # Diretório inicial
# super_bloco = Super_bloco()
# diretorio_atual = super_bloco.root
#
# # 1. Criar diretórios
# interpretar_comando("mkdir / documentos", diretorio_atual, super_bloco)
# interpretar_comando("mkdir / imagens", diretorio_atual, super_bloco)
#
# # 2. Listar diretório raiz
# interpretar_comando("ls /", diretorio_atual, super_bloco)
#
# # 3. Criar arquivos
# interpretar_comando("touch /documentos teste.txt", diretorio_atual, super_bloco)
# interpretar_comando("touch /documentos anotacoes.txt", diretorio_atual, super_bloco)
#
# # 4. Escrever nos arquivos
# interpretar_comando(
#     "echo /documentos teste.txt Olá_mundo!",
#     diretorio_atual,
#     super_bloco
# )
#
# interpretar_comando(
#     "echo /documentos anotacoes.txt Testando_sistema_de_arquivos",
#     diretorio_atual,
#     super_bloco
# )
#
# # 5. Ler arquivos
# interpretar_comando("cat /documentos teste.txt", diretorio_atual, super_bloco)
# interpretar_comando("cat /documentos anotacoes.txt", diretorio_atual, super_bloco)
#
# # 6. Verificar diretório
# interpretar_comando("ls /documentos", diretorio_atual, super_bloco)
#
# # 7. Sobrescrever arquivo
# interpretar_comando(
#     "echo /documentos teste.txt Novo_conteúdo!",
#     diretorio_atual,
#     super_bloco
# )
#
# # 8. Ler novamente
# interpretar_comando("cat /documentos teste.txt", diretorio_atual, super_bloco)
#
# # 9. Remover arquivo
# interpretar_comando("rm /documentos teste.txt", diretorio_atual, super_bloco)
#
# # 10. Verificar remoção
# interpretar_comando("ls /documentos", diretorio_atual, super_bloco)
#
# # 11. Remover arquivo restante
# interpretar_comando("rm /documentos anotacoes.txt", diretorio_atual, super_bloco)
#
# # 12. Remover diretórios vazios
# interpretar_comando("rmdir / documentos", diretorio_atual, super_bloco)
# interpretar_comando("rmdir / imagens", diretorio_atual, super_bloco)
#
# # 13. Verificar diretório raiz
# interpretar_comando("ls /", diretorio_atual, super_bloco)
#
# # 14. Verificar bitmaps
# print("\nBitmap de inodes:")
# print(super_bloco.bitmap_inodes)
#
# print("\nBitmap de blocos:")
# print(super_bloco.bitmap_blocos)
#
# # 15. Verificar tabela de inodes
# print("\nTabela de inodes:")
# print(super_bloco.tabela_inodes)