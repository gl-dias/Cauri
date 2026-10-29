"""Lotes de importação: a pré-visualização fica guardada até o usuário confirmar.

Cada lote tem os arquivos enviados (só um rótulo gerado, hash e tamanho: nem o
conteúdo nem o nome do arquivo são guardados) e as linhas já interpretadas, com o
rascunho de movimentação, o status e a decisão do usuário. Depois de gravado, cada
linha aponta para a movimentação criada.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from psycopg.types.json import Jsonb

from cauri_storage import Conn

BatchStatus = Literal["preview", "committed", "discarded"]
RowStatus = Literal["ok", "error", "already_imported", "possible_duplicate", "ignored"]
Decision = Literal["import", "keep_existing", "replace", "import_new"]


@dataclass(frozen=True, slots=True)
class StagedFile:
    label: str
    sha256: str
    size_bytes: int
    adapter: str
    adapter_version: int


@dataclass(frozen=True, slots=True)
class StagedRow:
    position: int
    line_numbers: tuple[int, ...]
    raw: Mapping[str, Any]
    status: RowStatus
    draft: Mapping[str, Any] | None = None
    idempotency_key: str | None = None
    messages: tuple[Mapping[str, Any], ...] = ()
    match_movement_ids: tuple[UUID, ...] = ()
    decision: Decision | None = None
    transfer: Mapping[str, Any] | None = None  # depósito ou saque: moeda, quantidade, dia


@dataclass(frozen=True, slots=True)
class StoredRow(StagedRow):
    id: UUID = field(default=UUID(int=0))
    file_id: UUID = field(default=UUID(int=0))
    movement_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class StoredFile:
    id: UUID
    label: str
    sha256: str
    size_bytes: int
    adapter: str
    adapter_version: int
    rows: tuple[StoredRow, ...]


@dataclass(frozen=True, slots=True)
class StoredBatch:
    id: UUID
    status: BatchStatus
    created_at: datetime
    finished_at: datetime | None
    warnings: tuple[str, ...]
    files: tuple[StoredFile, ...]
    suggestions: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class BatchSummary:
    id: UUID
    status: BatchStatus
    created_at: datetime
    finished_at: datetime | None
    labels: tuple[str, ...]
    imported: int


@dataclass(frozen=True, slots=True)
class ImportProfile:
    """Mapeamento de colunas salvo pelo usuário para um formato que o Cauri não conhecia.

    ``mapping``: campo do ledger -> nome da coluna no arquivo. ``options``: corretora fixa,
    formato de data e de número, moeda padrão. Nunca guarda conteúdo do arquivo.
    """

    id: UUID
    name: str
    mapping: Mapping[str, str]
    options: Mapping[str, Any]
    created_at: datetime
    last_used_at: datetime | None


class ImportStore:
    def __init__(self, conn: Conn) -> None:
        self._conn = conn

    # Perfis -------------------------------------------------------------------------

    def profiles(self, user_id: UUID) -> list[ImportProfile]:
        rows = self._conn.execute(
            "select id, name, mapping, options, created_at, last_used_at from imports.profiles"
            " where user_id = %s order by coalesce(last_used_at, created_at) desc, name",
            [user_id],
        ).fetchall()
        return [
            ImportProfile(
                id=r["id"],
                name=r["name"],
                mapping=r["mapping"],
                options=r["options"],
                created_at=r["created_at"],
                last_used_at=r["last_used_at"],
            )
            for r in rows
        ]

    def save_profile(
        self, user_id: UUID, name: str, mapping: Mapping[str, str], options: Mapping[str, Any]
    ) -> UUID:
        """Cria o perfil, ou atualiza o de mesmo nome."""
        row = self._conn.execute(
            "insert into imports.profiles (user_id, name, mapping, options)"
            " values (%s, %s, %s, %s)"
            " on conflict (user_id, name) do update set mapping = excluded.mapping,"
            "   options = excluded.options, updated_at = now()"
            " returning id",
            [user_id, name.strip(), Jsonb(dict(mapping)), Jsonb(dict(options))],
        ).fetchone()
        assert row is not None
        profile_id: UUID = row["id"]
        return profile_id

    def delete_profile(self, user_id: UUID, profile_id: UUID) -> bool:
        row = self._conn.execute(
            "delete from imports.profiles where user_id = %s and id = %s returning id",
            [user_id, profile_id],
        ).fetchone()
        return row is not None

    def touch_profiles(self, user_id: UUID, ids: Sequence[UUID]) -> None:
        if ids:
            self._conn.execute(
                "update imports.profiles set last_used_at = now()"
                " where user_id = %s and id = any(%s)",
                [user_id, list(ids)],
            )

    # Lotes --------------------------------------------------------------------------

    def create_batch(self, user_id: UUID, warnings: Sequence[str]) -> UUID:
        row = self._conn.execute(
            "insert into imports.batches (user_id, warnings) values (%s, %s) returning id",
            [user_id, Jsonb(list(warnings))],
        ).fetchone()
        assert row is not None
        batch_id: UUID = row["id"]
        return batch_id

    def add_file(self, user_id: UUID, batch_id: UUID, f: StagedFile) -> UUID:
        row = self._conn.execute(
            "insert into imports.files"
            " (batch_id, user_id, position, label, sha256, size_bytes, adapter, adapter_version)"
            " values (%s, %s,"
            "   (select count(*) from imports.files where batch_id = %s), %s, %s, %s, %s, %s)"
            " returning id",
            [
                batch_id,
                user_id,
                batch_id,
                f.label,
                f.sha256,
                f.size_bytes,
                f.adapter,
                f.adapter_version,
            ],
        ).fetchone()
        assert row is not None
        file_id: UUID = row["id"]
        return file_id

    def add_rows(self, user_id: UUID, file_id: UUID, rows: Sequence[StagedRow]) -> None:
        if not rows:
            return
        with self._conn.cursor() as cur:
            cur.executemany(
                "insert into imports.rows"
                " (file_id, user_id, position, line_numbers, raw, draft, idempotency_key,"
                "  status, messages, match_movement_ids, decision, transfer)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    [
                        file_id,
                        user_id,
                        r.position,
                        list(r.line_numbers),
                        Jsonb(dict(r.raw)),
                        Jsonb(dict(r.draft)) if r.draft is not None else None,
                        r.idempotency_key,
                        r.status,
                        Jsonb([dict(m) for m in r.messages]),
                        list(r.match_movement_ids),
                        r.decision,
                        Jsonb(dict(r.transfer)) if r.transfer is not None else None,
                    ]
                    for r in rows
                ],
            )

    def batch(self, user_id: UUID, batch_id: UUID) -> StoredBatch | None:
        conn = self._conn
        head = conn.execute(
            "select id, status, created_at, finished_at, warnings, suggestions from imports.batches"
            " where user_id = %s and id = %s",
            [user_id, batch_id],
        ).fetchone()
        if head is None:
            return None
        files = conn.execute(
            "select id, label, sha256, size_bytes, adapter, adapter_version"
            " from imports.files where user_id = %s and batch_id = %s order by position",
            [user_id, batch_id],
        ).fetchall()
        rows = conn.execute(
            "select r.* from imports.rows r join imports.files f on f.id = r.file_id"
            " where r.user_id = %s and f.batch_id = %s order by f.position, r.position",
            [user_id, batch_id],
        ).fetchall()
        by_file: dict[UUID, list[StoredRow]] = {f["id"]: [] for f in files}
        for r in rows:
            by_file[r["file_id"]].append(
                StoredRow(
                    id=r["id"],
                    file_id=r["file_id"],
                    position=r["position"],
                    line_numbers=tuple(r["line_numbers"]),
                    raw=r["raw"],
                    status=r["status"],
                    draft=r["draft"],
                    idempotency_key=r["idempotency_key"],
                    messages=tuple(r["messages"]),
                    match_movement_ids=tuple(r["match_movement_ids"]),
                    decision=r["decision"],
                    transfer=r["transfer"],
                    movement_id=r["movement_id"],
                )
            )
        return StoredBatch(
            id=head["id"],
            status=head["status"],
            created_at=head["created_at"],
            finished_at=head["finished_at"],
            warnings=tuple(head["warnings"]),
            suggestions=tuple(head["suggestions"]),
            files=tuple(
                StoredFile(
                    id=f["id"],
                    label=f["label"],
                    sha256=f["sha256"],
                    size_bytes=f["size_bytes"],
                    adapter=f["adapter"],
                    adapter_version=f["adapter_version"],
                    rows=tuple(by_file[f["id"]]),
                )
                for f in files
            ),
        )

    def recent(self, user_id: UUID, limit: int = 10) -> list[BatchSummary]:
        rows = self._conn.execute(
            "select b.id, b.status, b.created_at, b.finished_at,"
            "  coalesce(array_agg(f.label order by f.position)"
            "    filter (where f.id is not null), '{}') as labels,"
            "  (select count(*) from imports.rows r join imports.files f2 on f2.id = r.file_id"
            "    where f2.batch_id = b.id and r.movement_id is not null) as imported"
            " from imports.batches b left join imports.files f on f.batch_id = b.id"
            " where b.user_id = %s and b.status <> 'discarded'"
            " group by b.id order by b.created_at desc limit %s",
            [user_id, limit],
        ).fetchall()
        return [
            BatchSummary(
                id=r["id"],
                status=r["status"],
                created_at=r["created_at"],
                finished_at=r["finished_at"],
                labels=tuple(r["labels"]),
                imported=r["imported"],
            )
            for r in rows
        ]

    def set_suggestions(
        self, user_id: UUID, batch_id: UUID, suggestions: Sequence[Mapping[str, Any]]
    ) -> None:
        self._conn.execute(
            "update imports.batches set suggestions = %s where user_id = %s and id = %s",
            [Jsonb([dict(x) for x in suggestions]), user_id, batch_id],
        )

    def update_rows(self, user_id: UUID, rows: Sequence[StoredRow]) -> None:
        """Regrava status, mensagens, duplicados e decisão (depois de conferir de novo)."""
        if not rows:
            return
        with self._conn.cursor() as cur:
            cur.executemany(
                "update imports.rows set status = %s, messages = %s, match_movement_ids = %s,"
                "  decision = %s where user_id = %s and id = %s",
                [
                    [
                        r.status,
                        Jsonb([dict(m) for m in r.messages]),
                        list(r.match_movement_ids),
                        r.decision,
                        user_id,
                        r.id,
                    ]
                    for r in rows
                ],
            )

    def record_results(
        self,
        user_id: UUID,
        decisions: Mapping[UUID, Decision],
        movements: Mapping[UUID, UUID],
    ) -> None:
        """Guarda a decisão de cada linha e a movimentação que ela criou."""
        if not decisions and not movements:
            return
        with self._conn.cursor() as cur:
            cur.executemany(
                "update imports.rows set decision = coalesce(%s, decision),"
                "  movement_id = coalesce(%s, movement_id)"
                " where user_id = %s and id = %s",
                [
                    [decisions.get(row_id), movements.get(row_id), user_id, row_id]
                    for row_id in {*decisions, *movements}
                ],
            )

    def finish(
        self, user_id: UUID, batch_id: UUID, status: Literal["committed", "discarded"]
    ) -> bool:
        """Fecha um lote em pré-visualização. Devolve False se ele já estava fechado."""
        row = self._conn.execute(
            "update imports.batches set status = %s, finished_at = now()"
            " where user_id = %s and id = %s and status = 'preview' returning id",
            [status, user_id, batch_id],
        ).fetchone()
        return row is not None
