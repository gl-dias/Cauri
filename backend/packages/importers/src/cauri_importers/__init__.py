"""Importação de planilhas: B3 (Negociação e Movimentação), template genérico e exchange.

Contrato::

    result = importers.preview(ledger, user_id, [Upload(nome, conteúdo), ...])
    # a tela mostra result.batch: linhas boas, erros, já importadas e duplicados
    importers.commit(ledger, user_id, batch_id, {row_id: "replace", ...})
    importers.discard(ledger, user_id, batch_id)

Os arquivos nunca são guardados. Só as colunas que o adaptador conhece são lidas, então
CPF e nome do investidor não entram em lugar nenhum.
"""

from cauri_importers.service import (
    BatchClosedError,
    BatchNotFoundError,
    CommitRejectedError,
    CommitResult,
    FileProblem,
    ImportRejectedError,
    Preview,
    Upload,
    add_opening_balance,
    commit,
    discard,
    preview,
    recheck,
)

__all__ = [
    "BatchClosedError",
    "BatchNotFoundError",
    "CommitRejectedError",
    "CommitResult",
    "FileProblem",
    "ImportRejectedError",
    "Preview",
    "Upload",
    "add_opening_balance",
    "commit",
    "discard",
    "preview",
    "recheck",
]
