from interpretador import interpretar_comando, Super_bloco

super_bloco = Super_bloco()
diretorio_atual = super_bloco.root

while(1):
    diretorio_atual = interpretar_comando(input(f"{diretorio_atual}: "), diretorio_atual, super_bloco)