import hashlib
import metodos_arquivos as file

# assinaturas simuladas (padrões de bytes que identificam "malware")
ASSINATURAS = {
    b"MALWARE_SIG": "Simulado.Malware.A",
    b"VIRUS_SIM": "Simulado.Virus.B",
    b"TROJAN_SIM": "Simulado.Trojan.C",
}


def hash_bloco(dados):
    return hashlib.sha256(bytes(dados)).hexdigest()


def registrar_hashes(inode, super_bloco):
    """Registro oficial: hash de cada bloco do arquivo, no momento da gravação legítima."""
    inode.hashes_blocos = [
        hash_bloco(super_bloco.blocos[bloco].tobytes()) for bloco in inode.blocos
    ]


def coletar_arquivos(diretorio, caminho, super_bloco, saida):
    base = caminho.rstrip("/")
    for ref in diretorio.referencias:
        if isinstance(ref, file.Arquivo):
            saida.append((base + "/" + ref.nome, super_bloco.tabela_inodes[ref.inode_id]))
        else:
            coletar_arquivos(ref, base + "/" + ref.nome, super_bloco, saida)


def verificar_paridade(raid):
    """Em cada stripe, o XOR de todos os discos (dados + paridade) tem que ser zero."""
    inconsistentes = []
    for stripe in sorted(raid.known_stripes):
        try:
            blocos = [disco.read_block(stripe) for disco in raid.disks]
        except IOError:
            continue
        if any(raid.xor_blocks(blocos, raid.block_size)):
            inconsistentes.append(stripe)
    return inconsistentes


def auditar_bitmap(super_bloco):
    usados = {i for i, v in enumerate(super_bloco.bitmap_blocos) if v == 1}
    donos = set()
    for inode in super_bloco.tabela_inodes:
        if inode is not None:
            donos.update(inode.blocos)
    return sorted(usados - donos), sorted(donos - usados)


def simular_adulteracao(super_bloco, inode):
    """Simula um ataque físico: inverte um byte direto no disco, sem passar pelo FS."""
    if not inode.blocos:
        raise ValueError("Arquivo sem blocos para adulterar")
    raid = super_bloco.gerenciador_io.raid
    bloco = inode.blocos[0]
    stripe, disco = raid.locate_block(bloco)
    dados = bytearray(raid.disks[disco].blocks[stripe])
    dados[0] ^= 0xFF
    raid.disks[disco].blocks[stripe] = bytes(dados)
    return bloco, disco, stripe


def varrer(super_bloco, diretorio, caminho):
    io = super_bloco.gerenciador_io
    arquivos = []
    coletar_arquivos(diretorio, caminho, super_bloco, arquivos)

    print("[MÓDULO DE SEGURANÇA - VARREDURA DE INTEGRIDADE]")
    print(f"Analisando {len(arquivos)} arquivos em busca de assinaturas "
          "maliciosas e hashes corrompidos...")

    # uma única fila de leitura para todos os blocos (passa pelo escalonador FCFS)
    for _, inode in arquivos:
        for bloco in inode.blocos:
            io.solicitar_leitura(bloco)
    lidos = io.processar_fila()

    com_alerta = 0
    posicao = 0
    for caminho_arquivo, inode in arquivos:
        blocos_lidos = lidos[posicao:posicao + len(inode.blocos)]
        posicao += len(inode.blocos)

        blocos_alterados = []
        for i, dados in enumerate(blocos_lidos):
            esperado = inode.hashes_blocos[i] if i < len(inode.hashes_blocos) else None
            if esperado is None or hash_bloco(dados) != esperado:
                blocos_alterados.append(str(inode.blocos[i]))

        achadas = []
        if not inode.criptografado:
            conteudo = b"".join(blocos_lidos)[:inode.tamanho]
            for assinatura, nome in ASSINATURAS.items():
                if assinatura in conteudo:
                    achadas.append(nome)

        if blocos_alterados:
            print(f"- {caminho_arquivo} : [ALERTA] Hash do bloco "
                  f"{', '.join(blocos_alterados)} difere do registro oficial!")
            print("  Resultado: Possível modificação direta não autorizada no bloco do disco.")
        if achadas:
            print(f"- {caminho_arquivo} : [ALERTA] Assinatura maliciosa detectada: "
                  f"{', '.join(achadas)}")
        if blocos_alterados or achadas:
            com_alerta += 1
        else:
            estado = "Criptografado e Íntegro" if inode.criptografado else "Íntegro"
            print(f"- {caminho_arquivo} : [OK - {estado}]")

    print("--- Auditoria geral do volume ---")
    inconsistentes = verificar_paridade(io.raid)
    if inconsistentes:
        print(f"[ALERTA] Paridade RAID inconsistente nos stripes: {inconsistentes[:5]}")
    else:
        print(f"Paridade RAID: [OK] {len(io.raid.known_stripes)} stripes consistentes")

    orfaos, sem_bitmap = auditar_bitmap(super_bloco)
    if orfaos:
        print(f"[ALERTA] Blocos marcados como usados sem dono: {orfaos}")
    if sem_bitmap:
        print(f"[ALERTA] Blocos em uso por arquivos mas livres no bitmap: {sem_bitmap}")
    if not orfaos and not sem_bitmap:
        print("Bitmap de blocos: [OK] consistente com os inodes")

    print(f"Resumo: {len(arquivos)} arquivos analisados, {com_alerta} com alerta.")
    return com_alerta
