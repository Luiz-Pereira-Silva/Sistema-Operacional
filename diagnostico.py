"""Diagnóstico do disco (etapa 1), RAID e escalonamento de disco (etapa 2).

Comandos:
  tree [/caminho]                      árvore hierárquica do sistema de arquivos
  fs_status [--details]                mapa do disco, ocupação por arquivo e
                                       relatório de fragmentação (kernel)
  raid_status [--all]                  discos, paridade e distribuição dos blocos
  raid_fail <disco>                    força a falha de um disco (kernel)
  raid_rebuild <disco>                 reconstrói o disco via XOR (kernel)
  raid_test [<disco>]                  falha -> leitura via XOR -> reconstrução (kernel)
  disk_sched                           mostra o algoritmo de escalonamento atual
  disk_sched fcfs|sstf                 troca o algoritmo (kernel)
  disk_sched --demo "98,183,37" --head 53 [--algorithm sstf|fcfs]
                                       demonstra o escalonamento sem tocar no disco

Ligado ao resto só pelo gancho `diag.tratar(...)` em interpretador.py.
A segurança entra por duck typing: sem `sessao`, tudo roda como root.
"""

import metodos_arquivos as file
import metodos_diretorios as diretorios
from disk_simulator import ESCALONADORES, IORequest

COMANDOS = {"tree", "fs_status", "raid_status", "raid_fail", "raid_rebuild",
            "raid_test", "disk_sched"}

LER, EXECUTAR = 4, 1          # mesmos bits rwx de seguranca.py


# ------------------------------------------------------------------ utilidades
def _sessao(sb):
    return getattr(sb, "sessao", None)


def _exigir_kernel(sb, operacao):
    sessao = _sessao(sb)
    if sessao is not None:
        sessao.exigir_kernel(operacao)


def _exigir_acesso(sb, objeto, acao, caminho):
    sessao = _sessao(sb)
    if sessao is not None:
        sessao.verificar(objeto, acao, caminho)     # levanta PermissaoNegada


def _pode(sb, objeto, acao, caminho):
    try:
        _exigir_acesso(sb, objeto, acao, caminho)
        return True
    except Exception:
        return False


def _localizar_diretorio(sb, caminho):
    if not caminho.startswith("/"):
        raise ValueError("O caminho deve ser absoluto")
    alvo = sb.root
    _exigir_acesso(sb, alvo, EXECUTAR, "/")
    percorrido = ""
    for nome in caminho.split("/"):
        if not nome:
            continue
        for ref in alvo.referencias:
            if isinstance(ref, diretorios.Diretorio) and ref.nome == nome:
                alvo = ref
                break
        else:
            raise ValueError("Diretório inexistente")
        percorrido += "/" + nome
        _exigir_acesso(sb, alvo, EXECUTAR, percorrido)
    return alvo


def _percorrer(diretorio, caminho="/"):
    """Gera (caminho_completo, referência) de toda a árvore, em profundidade."""
    for ref in diretorio.referencias:
        completo = caminho.rstrip("/") + "/" + ref.nome
        yield completo, ref
        if isinstance(ref, diretorios.Diretorio):
            yield from _percorrer(ref, completo)


def _inodes_com_caminho(sb):
    """{inode_id: caminho} para todos os arquivos da árvore."""
    return {ref.inode_id: caminho
            for caminho, ref in _percorrer(sb.root) if isinstance(ref, file.Arquivo)}


def _formatar_permissoes(permissoes):
    texto = ""
    for deslocamento in (6, 3, 0):
        bits = (permissoes >> deslocamento) & 7
        texto += ("r" if bits & 4 else "-") + ("w" if bits & 2 else "-") + ("x" if bits & 1 else "-")
    return texto


# ------------------------------------------------------------------------ tree
def tree(sb, caminho="/"):
    raiz = _localizar_diretorio(sb, caminho)
    _exigir_acesso(sb, raiz, LER, caminho)
    print("\n[ÁRVORE DO SISTEMA DE ARQUIVOS]")
    print("/" if caminho.strip("/") == "" else "/" + caminho.strip("/"))

    def desenhar(diretorio, prefixo, caminho_atual):
        refs = diretorio.referencias
        for i, ref in enumerate(refs):
            ultimo = i == len(refs) - 1
            ramo = "└── " if ultimo else "├── "
            completo = caminho_atual.rstrip("/") + "/" + ref.nome
            if isinstance(ref, diretorios.Diretorio):
                legivel = _pode(sb, ref, LER, completo)
                nota = "" if legivel else " (acesso negado)"
                print(f"{prefixo}{ramo}{ref.nome}/ [DIR]{nota}")
                if legivel:
                    desenhar(ref, prefixo + ("    " if ultimo else "│   "), completo)
            else:
                inode = sb.tabela_inodes[ref.inode_id]
                extra = " [CRIPTOGRAFADO]" if getattr(inode, "criptografado", False) else ""
                print(f"{prefixo}{ramo}{ref.nome} ({inode.tamanho} B) [ARQ]{extra}")

    desenhar(raiz, "", caminho)
    print()


# -------------------------------------------------------------------- fs_status
def _corridas_livres(bitmap):
    """Lista de (inicio, tamanho) das lacunas de blocos livres consecutivos."""
    corridas, inicio = [], None
    for i, ocupado in enumerate(bitmap):
        if not ocupado and inicio is None:
            inicio = i
        elif ocupado and inicio is not None:
            corridas.append((inicio, i - inicio))
            inicio = None
    if inicio is not None:
        corridas.append((inicio, len(bitmap) - inicio))
    return corridas


def _faixa(inicio, fim):
    return f"{inicio:02d}" if inicio == fim else f"{inicio:02d}..{fim:02d}"


def fs_status(sb, detalhes=False):
    tb = file.tamanho_bloco
    total = len(sb.bitmap_blocos)
    caminhos = _inodes_com_caminho(sb)
    inodes = sorted((i for i in sb.tabela_inodes if i is not None), key=lambda i: i.inode_id)
    letras = {inode.inode_id: chr(ord("A") + n % 26) for n, inode in enumerate(inodes)}

    dono = {}                                  # bloco -> (inode, posição, total_de_blocos)
    for inode in inodes:
        for pos, bloco in enumerate(inode.blocos):
            dono[bloco] = (inode, pos, len(inode.blocos))

    print(f"\nTamanho do Bloco de Disco: {tb} B | Total de Blocos: {total} ({total * tb} B) | "
          f"I-nodes em uso: {len(inodes)}/{len(sb.bitmap_inodes)}")

    # ---- mapa gráfico
    print("\n[MAPA DE ALOCAÇÃO DO DISCO (Indexado)]")
    celulas = []
    for b in range(total):
        if b in dono:
            celulas.append(letras[dono[b][0].inode_id])
        elif sb.bitmap_blocos[b]:
            celulas.append("?")                # marcado no bitmap, sem dono
        else:
            celulas.append(".")
    por_linha = 10
    for inicio in range(0, total, por_linha):
        fim = min(inicio + por_linha, total)
        print(f"  {inicio:02d}-{fim - 1:02d} | " + " ".join(f"[{c}]" for c in celulas[inicio:fim]))
    legenda = [f"{letras[i.inode_id]} = {caminhos.get(i.inode_id, '(sem nome)')}" for i in inodes]
    print("  Legenda: " + (" | ".join(legenda) if legenda else "(nenhum arquivo)")
          + " | . = livre | ? = ocupado sem dono")

    # ---- detalhe bloco a bloco
    if detalhes:
        print("\n[DETALHE BLOCO A BLOCO]")
        b = 0
        while b < total:
            if b in dono:
                inode, pos, n = dono[b]
                usados = min(tb, inode.tamanho - pos * tb)
                print(f"Bloco {b:02d} [DADO]  : '{caminhos.get(inode.inode_id, '?')}' "
                      f"(Bloco {pos + 1}/{n} - {usados} bytes ocupados)")
                b += 1
            elif sb.bitmap_blocos[b]:
                print(f"Bloco {b:02d} [ÓRFÃO] : marcado no bitmap, sem arquivo associado")
                b += 1
            else:
                fim = b
                while fim + 1 < total and not sb.bitmap_blocos[fim + 1]:
                    fim += 1
                print(f"Bloco {_faixa(b, fim)}".ljust(14) + "         : [LIVRE]")
                b = fim + 1

        print("\n[TABELA DE I-NODES]")
        if not inodes:
            print("(vazia)")
        for inode in inodes:
            cripto = " | CRIPTOGRAFADO" if getattr(inode, "criptografado", False) else ""
            print(f"I-node {inode.inode_id:02d} : '{caminhos.get(inode.inode_id, '?')}' | "
                  f"{_formatar_permissoes(inode.permissoes)} ({inode.permissoes:o}) | "
                  f"uid {inode.dono_uid}/gid {inode.grupo_gid} | {inode.tamanho} B | "
                  f"blocos {inode.blocos}{cripto}")

    # ---- fragmentação interna
    print("\n--- RELATÓRIO DE FRAGMENTAÇÃO ---")
    print("Fragmentação Interna (espaço não usado no último bloco de cada arquivo):")
    total_interna = 0
    com_blocos = [i for i in inodes if i.blocos]
    if not com_blocos:
        print("  (nenhum arquivo com blocos alocados)")
    for inode in com_blocos:
        alocado = len(inode.blocos) * tb
        desperdicio = alocado - inode.tamanho
        total_interna += desperdicio
        usado_ultimo = inode.tamanho - (len(inode.blocos) - 1) * tb
        print(f"  '{caminhos.get(inode.inode_id, '?')}': real {inode.tamanho} B | "
              f"alocado {alocado} B ({len(inode.blocos)} bloco(s) de {tb} B) | "
              f"desperdício {desperdicio} B ({100 * desperdicio / tb:.0f}% no Bloco "
              f"{inode.blocos[-1]:02d}, {usado_ultimo}/{tb} B em uso)")
    print(f"Fragmentação Interna Total       : {total_interna} bytes")

    # ---- fragmentação externa
    livres = int(total - sum(1 for x in sb.bitmap_blocos if x))
    corridas = _corridas_livres(sb.bitmap_blocos)
    maior = max((t for _, t in corridas), default=0)
    lacunas = ": " + ", ".join(f"[{_faixa(i, i + t - 1)}]" for i, t in corridas) if corridas else ""
    print(f"Blocos livres                    : {livres} ({livres * tb} B) em {len(corridas)} lacuna(s){lacunas}")
    print(f"Maior lacuna contígua            : {maior} bloco(s) ({maior * tb} B)")
    print("Fragmentação Externa             : 0 bytes (i-node indexado: qualquer bloco livre "
          "pode ser usado por qualquer arquivo)")
    if len(corridas) > 1:
        print(f"  Obs.: com alocação CONTÍGUA, um arquivo maior que {maior * tb} B não caberia, "
              f"embora existam {livres * tb} B livres (fragmentação externa potencial).")
    print("Necessidade de Compactação       : NÃO (blocos alocados via i-node indexado)")

    meta = sb.gerenciador_io.metadata_blocks
    if meta:
        print(f"\nMetadados persistidos nos blocos lógicos 25..{24 + meta} do RAID ({meta} blocos).")
    print()


# ------------------------------------------------------------------------- RAID
def _raid(sb):
    return sb.gerenciador_io.raid


def raid_status(sb, todos=False):
    raid = _raid(sb)
    print(f"\nArranjo Ativo: RAID 5 ({raid.disk_count} Discos Físicos, Blocos de {raid.block_size} B)")
    print("[DISCOS] " + " | ".join(
        f"Disco {d.disk_id}: {'ONLINE' if d.online else 'FALHOU'}" for d in raid.disks))
    if any(not d.online for d in raid.disks):
        print("[MODO DEGRADADO] Leituras do disco falho são reconstruídas via XOR; "
              "escritas ficam bloqueadas até a reconstrução.")

    stripes = sorted(raid.known_stripes)
    print(f"\n[E/S - DISTRIBUIÇÃO EM DISCO] {len(stripes)} faixa(s) (stripe) gravada(s)")
    mostrar = stripes if todos else stripes[:6]
    for s in mostrar:
        ordem = raid.data_disk_order(s)
        paridade = raid.parity_disk(s)
        logicos = [s * raid.data_disks_per_stripe + i for i in range(len(ordem))]
        partes = {}
        for d, logico in zip(ordem, logicos):
            origem = "metadados" if logico >= len(sb.bitmap_blocos) else "dados"
            partes[d] = f"Bloco lógico {logico:02d} ({origem})"
        partes[paridade] = "PARIDADE: XOR(" + ", ".join(f"Bloco {n:02d}" for n in logicos) + ")"
        print(f"Faixa {s:02d} | " + " | ".join(
            f"Disco {d}: [{partes[d]}]" + ("" if raid.disks[d].online else " *FALHOU*")
            for d in range(raid.disk_count)))
    if not todos and len(stripes) > len(mostrar):
        print(f"... mais {len(stripes) - len(mostrar)} faixa(s) (use 'raid_status --all')")
    print()


def raid_fail(sb, disco):
    raid = _raid(sb)
    raid.validate_disk_id(disco)
    if not raid.disks[disco].online:
        raise ValueError(f"O Disco {disco} já está indisponível")
    if any(not d.online for d in raid.disks):
        raise IOError("RAID 5 não suporta falha simultânea de dois discos")
    raid.fail_disk(disco)
    print(f"* Falha forçada no Disco {disco}! O arranjo opera em modo degradado.")


def raid_rebuild(sb, disco):
    raid = _raid(sb)
    raid.rebuild_disk(disco)
    print(f"* Disco {disco} reconstruído via XOR dos demais discos "
          f"({len(raid.known_stripes)} faixa(s)) [OK]. Arranjo normalizado.")


def raid_test(sb, disco=1):
    raid = _raid(sb)
    raid.validate_disk_id(disco)
    if any(not d.online for d in raid.disks):
        raise IOError("Há disco indisponível: reconstrua-o antes de rodar o teste")
    if not raid.known_stripes:
        raise ValueError("Nenhum dado gravado no RAID ainda: crie arquivos antes do teste")

    original = {d.disk_id: dict(d.blocks) for d in raid.disks}
    print(f"\nArranjo Ativo: RAID 5 ({raid.disk_count} Discos Físicos, Blocos de {raid.block_size} B)")
    print("\n[TESTE DE FALHA SIMULADO]")
    raid.fail_disk(disco)
    print(f"* Falha forçada no Disco {disco}!")

    reconstruidos = falhas = mostrados = 0
    try:
        for s in sorted(raid.known_stripes):
            if raid.parity_disk(s) == disco:
                continue                           # esta faixa só tinha paridade no disco falho
            logico = s * raid.data_disks_per_stripe + raid.data_disk_order(s).index(disco)
            lido = raid.read_block(logico)         # disco offline: reconstrução via XOR
            ok = lido == original[disco].get(s, bytes(raid.block_size))
            reconstruidos += 1
            falhas += 0 if ok else 1
            if mostrados < 5 or not ok:
                outros = " XOR ".join(f"Disco {d.disk_id}" for d in raid.disks if d.disk_id != disco)
                print(f"* Recuperando Bloco {logico:02d} via operação XOR: ({outros}) "
                      f"-> Reconstrução [{'OK' if ok else 'FALHOU'}]")
                mostrados += 1
        if reconstruidos > mostrados:
            print(f"* ... e mais {reconstruidos - mostrados} bloco(s) reconstruído(s)")
    finally:
        raid.rebuild_disk(disco)
    integro = all(raid.disks[i].blocks == original[i] for i in range(raid.disk_count))
    print(f"* Disco {disco} reconstruído: conteúdo idêntico ao original [{'OK' if integro else 'FALHOU'}]")
    print(f"Resultado: {reconstruidos - falhas}/{reconstruidos} bloco(s) recuperado(s) sem perda de dados.\n")


# ------------------------------------------------------------------ disk_sched
def _demo_escalonamento(trilhas, cabeca, algoritmo):
    escalonador = ESCALONADORES[algoritmo]
    res = escalonador.schedule([IORequest(track=t) for t in trilhas], cabeca)
    descr = {"FCFS": "First Come First Served", "SSTF": "Shortest Seek Time First"}[escalonador.nome]
    print(f"\n[E/S] Requisições de leitura/escrita pendentes nas trilhas: {trilhas}")
    print(f"Posição atual da cabeça de leitura: Trilha {cabeca}")
    print(f"\n--- ESCALONAMENTO DE DISCO: {escalonador.nome} ({descr}) ---")
    print("Ordem de Atendimento : " + " -> ".join(map(str, res.order)))
    formula = " + ".join(f"|{a}-{b}|" for a, b in zip(res.order, res.order[1:]))
    soma = " + ".join(map(str, res.movements))
    print(f"Deslocamento da Cabeça: {formula}")
    print(f"Total de Movimento    : {soma} = {res.total_movement} trilhas")


def disk_sched(sb, op):
    io = sb.gerenciador_io
    if "demo" in op:
        try:
            trilhas = [int(x) for x in str(op["demo"]).replace(" ", "").split(",") if x != ""]
            cabeca = int(op.get("head", io.cabeca))
        except ValueError:
            raise ValueError('Use: disk_sched --demo "98,183,37,122,14" --head 53 [--algorithm sstf|fcfs]')
        if not trilhas or any(t < 0 for t in trilhas) or cabeca < 0:
            raise ValueError("Informe ao menos uma trilha (inteiros não negativos)")
        algoritmo = str(op.get("algorithm", getattr(io.scheduler, "nome", "FCFS"))).lower()
        if algoritmo not in ESCALONADORES:
            raise ValueError("Algoritmo inválido (use fcfs ou sstf)")
        _demo_escalonamento(trilhas, cabeca, algoritmo)
        print()
        return
    novo = op.get("_posicional")
    if novo is None:
        print(f"Algoritmo de escalonamento de disco: {getattr(io.scheduler, 'nome', 'FCFS')} "
              f"(disponíveis: {', '.join(n.upper() for n in ESCALONADORES)}) | "
              f"cabeça na trilha {io.cabeca}")
        return
    novo = novo.lower()
    if novo not in ESCALONADORES:
        raise ValueError("Algoritmo inválido (use fcfs ou sstf)")
    _exigir_kernel(sb, "disk_sched (troca de algoritmo)")
    io.scheduler = ESCALONADORES[novo]()
    print(f"Escalonador de disco definido: {io.scheduler.nome}")


# ---------------------------------------------------------------------- despacho
def _flags(argumentos):
    """--chave valor / --chave (vira True) / primeiro argumento solto em '_posicional'."""
    op, i = {}, 0
    while i < len(argumentos):
        a = argumentos[i]
        if a.startswith("--"):
            if i + 1 < len(argumentos) and not argumentos[i + 1].startswith("--"):
                op[a[2:]] = argumentos[i + 1]
                i += 2
            else:
                op[a[2:]] = True
                i += 1
        else:
            op.setdefault("_posicional", a)
            i += 1
    return op


def _inteiro(texto, nome):
    try:
        return int(texto)
    except (TypeError, ValueError):
        raise ValueError(f"{nome} deve ser um número inteiro")


def tratar(comando, partes, sb):
    """Executa o comando se for de diagnóstico. Devolve True se tratou."""
    if comando not in COMANDOS:
        return False
    op = _flags(partes[1:])

    if comando == "tree":
        tree(sb, op.get("_posicional", "/"))
    elif comando == "fs_status":
        _exigir_kernel(sb, "fs_status")
        fs_status(sb, detalhes="details" in op)
    elif comando == "raid_status":
        raid_status(sb, todos="all" in op)
    elif comando == "raid_fail":
        _exigir_kernel(sb, "raid_fail")
        raid_fail(sb, _inteiro(op.get("_posicional"), "O disco"))
    elif comando == "raid_rebuild":
        _exigir_kernel(sb, "raid_rebuild")
        raid_rebuild(sb, _inteiro(op.get("_posicional"), "O disco"))
    elif comando == "raid_test":
        _exigir_kernel(sb, "raid_test")
        raid_test(sb, _inteiro(op.get("_posicional", 1), "O disco"))
    elif comando == "disk_sched":
        disk_sched(sb, op)
    return True
