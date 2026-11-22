import sys

from interpretador import interpretar_comando, Super_bloco

# uso: python main.py [--frames N]   (menos molduras = page faults/substituições mais cedo)
frames = int(sys.argv[sys.argv.index("--frames") + 1]) if "--frames" in sys.argv else None
super_bloco = Super_bloco(num_molduras=frames)
diretorio_atual = super_bloco.root

while True:
    comando = input(f"{diretorio_atual}: ")
    if comando.strip() in ("exit", "sair"):
        break
    diretorio_atual = interpretar_comando(comando, diretorio_atual, super_bloco)
