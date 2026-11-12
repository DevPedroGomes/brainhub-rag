"""Semeia o acervo de demonstração numa conta, pelo caminho real de ingestão.

POR QUE
-------
A demo do BrainHub não se sustenta com três PDFs: qualquer pessoa faz isso no chat
de um provedor, com uma experiência melhor. O que um provedor não faz é acervo,
com centenas de documentos indexados, versões que se contradizem e vigência no
tempo. Este script põe esse acervo de pé.

COMO
----
Espelha exatamente o que `POST /documents/upload` faz, na mesma ordem:

    save_file()  ->  INSERT em documents  ->  enfileirar("ingerir", ...)

Não chama a rota HTTP de propósito: ela exige JWT, aplica rate limit por IP e
consome a cota diária de visitante. Nada disso deveria valer para uma operação
de manutenção feita pelo operador.

⚠️ O TETO DIÁRIO É DELIBERADAMENTE PULADO
------------------------------------------
`metering.consumir("ingest", ...)` existe para impedir que UM VISITANTE torre o
orçamento do dia. Semear é o operador enchendo a própria conta de demonstração:
consumir a cota aqui bloquearia o script no documento 100 e ainda deixaria a demo
sem cota para o resto do dia, que é o oposto do que o teto existe para proteger.
O gasto real continua acontecendo e continua sendo do operador: use `--limite`
para semear em lotes e `--estimar` para ver o tamanho antes.

⚠️ O LIMITE DE TAXA DA VOYAGE MANDA NO RITMO
-------------------------------------------
A Voyage limita requisições por minuto, e o limite depende da conta. Como a
ingestão faz uma chamada de embedding por documento, semear acima do limite faz
o job estourar a retentativa e cair na dead-letter. Use `--rpm`, que espaça o
enfileiramento para caber no limite.

IDEMPOTENTE
-----------
A chave é o título, entre os documentos marcados com `meta.acervo = "demo"`. Rodar
de novo pula o que já existe, então um lote interrompido continua de onde parou sem
duplicar chunk nem pagar embedding duas vezes.

DATA DE VIGÊNCIA
----------------
O recorte `as_of` corta por `effective_date`. Documento sem ela cai na data do
upload, e o acervo inteiro subiu no mesmo dia: ele some de toda pergunta sobre o
passado. Por isso cada execução confere o que já foi semeado e devolve a data a
quem ficou sem, lendo o cabeçalho do próprio texto ("Emitido em: AAAA-MM-DD").
`--estimar` mostra quantos estão sem data; `--corrigir` faz só a conferência, sem
enfileirar nada nem gastar.

SENHA DA CONTA
--------------
Nao ha senha padrao: o repositorio e publico, e uma senha escrita aqui seria a
senha da conta demo para qualquer um. Toda operacao que pode criar a conta exige
`--senha` ou a env `ACERVO_DEMO_SENHA`, com pelo menos 16 caracteres. So
`--estimar` dispensa, porque nao escreve nada.

USO
    python -m scripts.semear_acervo_demo --email demo@gomio.com.br --estimar
    ACERVO_DEMO_SENHA=... python -m scripts.semear_acervo_demo --email demo@gomio.com.br --limite 50
    python -m scripts.semear_acervo_demo --email demo@gomio.com.br --senha ...
    ACERVO_DEMO_SENHA=... python -m scripts.semear_acervo_demo --email demo@gomio.com.br --corrigir
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

from sqlalchemy import insert, select
from sqlalchemy import text as sqltext

from app.config.settings import get_settings
from app.db.engine import engine
from app.db.models import documents, users
from app.services.file_storage import save_file
from scripts.gerar_acervo_demo import Documento, gerar

MIME_PDF = "application/pdf"
MINIMO_SENHA = 16
MARCA = "demo"
"""Valor de `meta.acervo` nos documentos semeados.

Serve a duas coisas: torna a semeadura idempotente sem tabela nova, e deixa
`--limpar` apagar o acervo sem tocar em documento que a pessoa subiu à mão. Fica
em `meta`, e não no título, porque o título aparece na lista e na citação.
"""
PREFIXO_ANTIGO = "[acervo-demo] "
"""Prefixo de título que marcava o documento semeado antes da marca em `meta`."""
DO_ACERVO = "user_id = :u AND meta->>'acervo' = :marca"
DATA_NO_CABECALHO = r"Emitido em: ([0-9]{4}-[0-9]{2}-[0-9]{2})"


def senha_da_conta(argumento: str | None) -> str:
    """A senha vinda de `--senha` ou de `ACERVO_DEMO_SENHA`; sem ela, encerra."""
    senha = argumento or os.environ.get("ACERVO_DEMO_SENHA") or ""
    if len(senha) < MINIMO_SENHA:
        raise SystemExit(
            f"defina a senha da conta demo com --senha ou ACERVO_DEMO_SENHA "
            f"(minimo {MINIMO_SENHA} caracteres); nao ha senha padrao"
        )
    return senha


def _hash_senha(senha: str) -> str:
    # Importado do módulo de auth para não existirem dois jeitos de derivar o
    # hash. Se o algoritmo mudar lá, muda aqui junto.
    from app.api.routes.auth import _hash_password

    return _hash_password(senha)


def buscar_usuario(email: str) -> str | None:
    with engine.begin() as conn:
        existente = conn.execute(select(users.c.id).where(users.c.email == email)).scalar()
    return str(existente) if existente else None


def garantir_usuario(email: str, senha: str) -> str:
    """Devolve o `user_id` da conta de demonstração, criando-a se preciso."""
    with engine.begin() as conn:
        existente = conn.execute(select(users.c.id).where(users.c.email == email)).scalar()
        if existente:
            return str(existente)

        user_id = str(uuid.uuid4())
        conn.execute(
            insert(users).values(
                id=user_id,
                email=email,
                password_hash=_hash_senha(senha),
                full_name="Aurora Coffee Roasters (demonstração)",
            )
        )
        return user_id


def _parametros(user_id: str) -> dict:
    return {"u": user_id, "marca": MARCA, "p": PREFIXO_ANTIGO, "n": len(PREFIXO_ANTIGO) + 1}


def ja_semeados(user_id: str) -> set[str]:
    """Títulos já semeados, contando os que ainda têm o prefixo antigo."""
    with engine.begin() as conn:
        linhas = conn.execute(
            sqltext(
                "SELECT CASE WHEN starts_with(title, :p) THEN substr(title, :n) ELSE title END "
                f"FROM documents WHERE ({DO_ACERVO}) OR (user_id = :u AND starts_with(title, :p))"
            ),
            _parametros(user_id),
        ).fetchall()
    return {linha[0] for linha in linhas}


def adotar_titulos_antigos(user_id: str) -> int:
    """Tira o prefixo antigo do título e grava a marca em `meta`. Idempotente."""
    with engine.begin() as conn:
        n = conn.execute(
            sqltext(
                "UPDATE documents SET title = substr(title, :n), "
                "meta = COALESCE(meta, '{}'::jsonb) || jsonb_build_object('acervo', CAST(:marca AS text)) "
                "WHERE user_id = :u AND starts_with(title, :p)"
            ),
            _parametros(user_id),
        ).rowcount
    return int(n or 0)


def sem_data(user_id: str) -> int:
    """Quantos documentos semeados estão sem `effective_date`."""
    with engine.begin() as conn:
        return int(conn.execute(
            sqltext(
                "SELECT count(*) FROM documents "
                f"WHERE (({DO_ACERVO}) OR (user_id = :u AND starts_with(title, :p))) "
                "AND effective_date IS NULL"
            ),
            _parametros(user_id),
        ).scalar_one())


def restaurar_datas(user_id: str) -> int:
    """Devolve a `effective_date` ao documento semeado que ficou sem ela.

    A data sai do cabeçalho do texto indexado, no primeiro chunk que o traz, e
    não do gerador: o gerador só reproduz o mesmo documento com a mesma
    `--quantidade`, e o cabeçalho é o próprio documento. Documento ainda sem
    chunk fica para a próxima execução. `meta.emitido_em` volta junto.
    """
    with engine.begin() as conn:
        n = conn.execute(
            sqltext(
                "UPDATE documents d SET effective_date = CAST(c.emitido AS date), "
                "meta = COALESCE(d.meta, '{}'::jsonb) || jsonb_build_object('emitido_em', c.emitido) "
                "FROM (SELECT DISTINCT ON (document_id) document_id, "
                "substring(content FROM :padrao) AS emitido "
                "FROM chunks WHERE user_id = :u AND content ~ :padrao "
                "ORDER BY document_id, page, chunk_index) c "
                "WHERE d.id = c.document_id AND d.user_id = :u "
                "AND d.meta->>'acervo' = :marca AND d.effective_date IS NULL"
            ),
            {**_parametros(user_id), "padrao": DATA_NO_CABECALHO},
        ).rowcount
    return int(n or 0)


async def reprocessar(user_id: str, rpm: float = 0) -> int:
    """Reenfileira o que ficou em `pending` ou `failed`.

    Semeadura sob limite de taxa SEMPRE deixa retardatário: o job estoura a
    retentativa e cai na dead-letter, ou fica preso em `pending` porque a fila
    desistiu. Sem isto, a única saída seria limpar tudo e pagar o embedding de
    novo no acervo inteiro para recuperar dois documentos.
    """
    from agent_ops.decisions import digerir
    from agent_ops.queue import criar_pool, enfileirar

    with engine.begin() as conn:
        linhas = conn.execute(
            sqltext(
                "SELECT id, storage_path FROM documents "
                f"WHERE {DO_ACERVO} AND status IN ('pending','failed')"
            ),
            _parametros(user_id),
        ).fetchall()

    if not linhas:
        return 0

    fila = await criar_pool()
    intervalo = 60.0 / rpm if rpm > 0 else 0.0
    for doc_id, storage_path in linhas:
        # Volta para `pending` antes de reenfileirar: `failed` que continua
        # `failed` na fila esconde se o reprocessamento sequer começou.
        with engine.begin() as conn:
            conn.execute(
                sqltext("UPDATE documents SET status = 'pending' WHERE id = :id"), {"id": doc_id}
            )
        digest = digerir(f"reprocesso:{doc_id}:{storage_path}")
        await enfileirar(
            fila, "ingerir", str(doc_id), user_id, storage_path,
            digest=digest, tenant=user_id,
        )
        if intervalo:
            await asyncio.sleep(intervalo)
    return len(linhas)


def limpar(user_id: str) -> int:
    """Apaga só o que este script semeou. `chunks` cai por ON DELETE CASCADE."""
    with engine.begin() as conn:
        n = conn.execute(
            sqltext(f"DELETE FROM documents WHERE {DO_ACERVO}"), _parametros(user_id)
        ).rowcount
    return int(n or 0)


async def semear(user_id: str, docs: list[Documento], destino_pdf: Path, rpm: float = 0) -> tuple[int, int]:
    """Grava, registra e enfileira. Devolve (semeados, pulados)."""
    # Import tardio e a MESMA fila que a app usa: `criar_pool` do agent-ops, do
    # jeito que `app/main.py` faz no lifespan. Uma fila diferente aqui semearia
    # numa fila que worker nenhum consome.
    from agent_ops.decisions import digerir
    from agent_ops.queue import criar_pool, enfileirar

    existentes = ja_semeados(user_id)
    fila = await criar_pool()
    semeados = pulados = 0

    # O freio fica no ENFILEIRAMENTO, e nao no worker, porque a fila e FIFO e o
    # worker puxa um job por vez: espacar a entrada espaca o consumo, sem tocar
    # no worker nem inventar um segundo lugar onde o ritmo e decidido.
    intervalo = 60.0 / rpm if rpm > 0 else 0.0

    for doc in docs:
        titulo = doc.titulo
        if titulo in existentes:
            pulados += 1
            continue

        pdf = destino_pdf / Path(doc.nome_arquivo).with_suffix(".pdf").name
        if not pdf.is_file():
            print(f"  ! sem PDF para {doc.nome_arquivo}, pulando", file=sys.stderr)
            pulados += 1
            continue

        storage_path = save_file(user_id, MIME_PDF, pdf.read_bytes())
        with engine.begin() as conn:
            doc_id = conn.execute(
                insert(documents)
                .values(
                    user_id=user_id,
                    title=titulo,
                    mime=MIME_PDF,
                    storage_path=storage_path,
                    status="pending",
                    # A data de emissao e o que da sentido ao recorte no tempo:
                    # `as_of` corta por `effective_date`. O acervo inteiro sobe no
                    # mesmo dia, entao sem ela "e em marco de 2025?" nao acharia
                    # nada. `meta.emitido_em` fica como registro de origem.
                    meta={
                        "emitido_em": doc.emitido_em.isoformat(),
                        "categoria": doc.categoria,
                        "acervo": MARCA,
                    },
                    effective_date=doc.emitido_em,
                )
                .returning(documents.c.id)
            ).scalar_one()

        # O digest identifica ESTA ingestao (linha + arquivo), como no upload:
        # `doc_id` e `storage_path` sao novos a cada semeadura, entao ele da um
        # `job_id` deterministico sem prometer dedup entre execucoes. A
        # idempotencia deste script vem do titulo, nao daqui.
        digest = digerir(f"{doc_id}:{storage_path}")
        await enfileirar(
            fila, "ingerir", str(doc_id), user_id, storage_path,
            digest=digest, tenant=user_id,
        )
        semeados += 1
        if semeados % 25 == 0:
            print(f"  {semeados} enfileirados...", flush=True)
        if intervalo:
            await asyncio.sleep(intervalo)

    return semeados, pulados


def main() -> None:
    p = argparse.ArgumentParser(description="Semeia o acervo de demonstração da Aurora.")
    # NAO usar TLD reservado (.local, .test, .example, .invalid): o `email-validator`
    # que valida o /auth/login recusa todos eles. A conta criada direto por SQL
    # existiria e nunca conseguiria entrar.
    p.add_argument("--email", default="demo@gomio.com.br")
    p.add_argument("--senha", default=None,
                   help=f"senha da conta demo (ou env ACERVO_DEMO_SENHA), minimo {MINIMO_SENHA} caracteres")
    p.add_argument("--quantidade", type=int, default=500)
    p.add_argument("--limite", type=int, default=0, help="semeia no máximo N nesta execução (0 = todos)")
    p.add_argument("--rpm", type=float, default=0,
                   help="espaça o enfileiramento para N documentos por minuto (0 = sem freio). "
                        "Use o limite de requisições por minuto da conta Voyage.")
    p.add_argument("--pdfs", type=Path, default=Path("/tmp/acervo-demo"))
    p.add_argument("--estimar", action="store_true", help="não escreve nada; só diz o tamanho do trabalho")
    p.add_argument("--limpar", action="store_true", help="apaga o acervo semeado desta conta e sai")
    p.add_argument("--reprocessar", action="store_true",
                   help="reenfileira os documentos que ficaram em pending ou failed, e sai")
    p.add_argument("--corrigir", action="store_true",
                   help="só ajusta título e data do que já foi semeado, e sai; não enfileira nada")
    args = p.parse_args()

    # Antes de gerar ou tocar no banco: sem senha, nada acontece.
    senha = None if args.estimar else senha_da_conta(args.senha)
    docs = gerar(args.quantidade)

    # `--estimar` nao pode escrever nada, nem criar a conta: um dry-run que deixa
    # rastro no banco perde a serventia de ser um dry-run.
    if args.estimar:
        user_id = buscar_usuario(args.email)
        existentes = ja_semeados(user_id) if user_id else set()
        pendentes = [d for d in docs if d.titulo not in existentes]
        if args.limite:
            pendentes = pendentes[: args.limite]
        print(f"conta:        {args.email}  ({user_id or 'ainda nao existe'})")
        print(f"no acervo:    {len(docs)}")
        print(f"ja semeados:  {len(existentes)}")
        print(f"sem data:     {sem_data(user_id) if user_id else 0}")
        print(f"a semear:     {len(pendentes)}")
        print(f"custo:        ~1 chunk por documento, entao ~{len(pendentes)} enriquecimentos")
        print(f"              + ~{len(pendentes)} chamadas de embedding (uma por documento)")
        return

    user_id = garantir_usuario(args.email, senha)

    # Antes do `--limpar`, que apaga pela marca em `meta`.
    adotados = adotar_titulos_antigos(user_id)
    if adotados:
        print(f"{adotados} títulos sem o prefixo antigo")

    if args.limpar:
        print(f"{limpar(user_id)} documentos removidos de {args.email}")
        return

    restaurados = restaurar_datas(user_id)
    if restaurados:
        print(f"{restaurados} documentos voltaram a ter data de vigência")
    if args.corrigir:
        print(f"sem data:     {sem_data(user_id)}")
        return

    if args.reprocessar:
        n = asyncio.run(reprocessar(user_id, args.rpm))
        print(f"{n} documentos reenfileirados")
        return

    existentes = ja_semeados(user_id)
    pendentes = [d for d in docs if d.titulo not in existentes]
    if args.limite:
        pendentes = pendentes[: args.limite]

    if not args.pdfs.is_dir():
        raise SystemExit(
            f"{args.pdfs} não existe. Gere o acervo primeiro:\n"
            f"  python -m scripts.gerar_acervo_demo --saida {args.pdfs} "
            f"--quantidade {args.quantidade} --formato pdf"
        )

    if args.rpm:
        minutos = len(pendentes) / args.rpm
        print(f"freio de {args.rpm}/min: {len(pendentes)} documentos levam ~{minutos:.0f} minutos\n", flush=True)

    semeados, pulados = asyncio.run(semear(user_id, pendentes, args.pdfs, args.rpm))
    print(f"\n{semeados} enfileirados, {pulados} pulados")
    print(f"conta: {args.email}  ({user_id})")
    print("acompanhe: docker logs -f group-documents-worker")


if __name__ == "__main__":
    main()
