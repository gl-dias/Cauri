"""Leitura de planilha (.xlsx ou .csv) reduzida às colunas que o adaptador conhece.

O cabeçalho decide o adaptador. Depois disso, só as colunas declaradas por ele são
lidas: CPF, nome, endereço ou qualquer outra coluna do arquivo nunca saem daqui.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Generator, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import PurePath

from cauri_importers.model import Adapter, Cell, SheetRow
from cauri_importers.privacy import normalize, scrub

MAX_BYTES = 5 * 1024 * 1024
MAX_UNZIPPED_BYTES = 80 * 1024 * 1024  # .xlsx é zip: limite contra arquivo-bomba
MAX_ROWS = 20_000
HEADER_SCAN = 30
_NUMERIC_TEXT = re.compile(r"^-?[\d.,]+$")


class FileError(ValueError):
    """Arquivo que não dá para ler. A mensagem vai direto para a tela."""


class UnknownFormatError(FileError):
    """Arquivo legível, mas de formato desconhecido. Leva os nomes das colunas do cabeçalho
    provável, para o usuário mapear (só os nomes: nenhum valor do arquivo)."""

    def __init__(self, message: str, columns: list[str]) -> None:
        super().__init__(message)
        self.columns = columns


@dataclass(frozen=True, slots=True)
class Detected:
    adapter: Adapter
    rows: list[SheetRow]


def read(filename: str, content: bytes, adapters: Sequence[Adapter]) -> Detected:
    if not content:
        raise FileError("Arquivo vazio.")
    if len(content) > MAX_BYTES:
        raise FileError("Arquivo maior que 5 MB. Exporte um período menor.")
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".xlsx":
        sheets = _xlsx_sheets(content)
    elif suffix in {".csv", ".txt"}:
        sheets = _csv_sheets(content)
    elif suffix == ".xls":
        raise FileError("Formato .xls antigo: abra no Excel e salve como .xlsx.")
    else:
        raise FileError("Formato não suportado. Envie .xlsx ou .csv.")

    best_header: list[str] = []
    try:
        for rows in sheets:
            detected = _detect(rows, adapters)
            if isinstance(detected, Detected):
                return detected
            if len(detected) > len(best_header):
                best_header = detected
    finally:
        sheets.close()  # fecha a planilha mesmo se der erro no meio
    raise UnknownFormatError(
        "Não reconheci o formato deste arquivo. Associe as colunas aos campos do Cauri e "
        "salve um perfil: da próxima vez ele é reconhecido sozinho.",
        best_header,
    )


def _detect(
    rows: Iterator[tuple[int, list[Cell]]], adapters: Sequence[Adapter]
) -> Detected | list[str]:
    """O adaptador e as linhas, ou (sem adaptador) o cabeçalho provável: a linha do início
    com mais células de texto e nenhum número ou data, que é onde ficam os nomes."""
    scanned: list[tuple[int, list[Cell]]] = []
    guess: list[str] = []
    for number, cells in rows:
        scanned.append((number, cells))
        texts = [c.strip() for c in cells if isinstance(c, str) and c.strip()]
        if len(texts) > len(guess) and not any(isinstance(c, Decimal | date) for c in cells):
            guess = [scrub(t)[:80] for t in texts][:60]
        header = [normalize(c) if isinstance(c, str) else "" for c in cells]
        best: tuple[Adapter, dict[int, str]] | None = None
        for adapter in adapters:
            mapping = _match(header, adapter)
            if adapter.required <= set(mapping.values()) and (
                best is None or len(mapping) > len(best[1])
            ):
                best = (adapter, mapping)
        if best is not None:
            adapter, mapping = best
            return Detected(adapter=adapter, rows=_body(rows, mapping))
        if len(scanned) >= HEADER_SCAN:
            return guess
    return guess


def _match(header: list[str], adapter: Adapter) -> dict[int, str]:
    """Índice da coluna no arquivo -> coluna canônica do adaptador."""
    mapping: dict[int, str] = {}
    for index, text in enumerate(header):
        if not text:
            continue
        for canonical, spellings in adapter.columns.items():
            if text in spellings and canonical not in mapping.values():
                mapping[index] = canonical
                break
    return mapping


def _body(rows: Iterable[tuple[int, list[Cell]]], mapping: dict[int, str]) -> list[SheetRow]:
    body: list[SheetRow] = []
    for number, cells in rows:
        picked = {
            canonical: _clean(cells[index]) if index < len(cells) else None
            for index, canonical in mapping.items()
        }
        if all(v is None for v in picked.values()):
            continue
        body.append(SheetRow(number=number, cells=picked))
        if len(body) > MAX_ROWS:
            raise FileError(f"Arquivo com mais de {MAX_ROWS} linhas. Exporte um período menor.")
    return body


def _clean(value: Cell) -> Cell:
    if isinstance(value, str):
        text = value.strip()
        if not text or text == "-":
            return None
        # Texto livre nunca carrega nada com cara de CPF. Número fica como veio.
        return text if _NUMERIC_TEXT.match(text) else scrub(text)
    return value


def as_text(value: Cell) -> str:
    """Forma textual de uma célula, para guardar no ``raw`` da linha."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return f"{value:%d/%m/%Y %H:%M:%S}" if value.time() != time() else f"{value:%d/%m/%Y}"
    if isinstance(value, date):
        return f"{value:%d/%m/%Y}"
    return str(value)


# xlsx -------------------------------------------------------------------------------


def _xlsx_sheets(content: bytes) -> Generator[Iterator[tuple[int, list[Cell]]]]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if sum(i.file_size for i in archive.infolist()) > MAX_UNZIPPED_BYTES:
                raise FileError("Planilha grande demais depois de descompactada.")
    except zipfile.BadZipFile as exc:
        raise FileError("Arquivo .xlsx corrompido ou de outro formato.") from exc

    import openpyxl  # carregado só quando precisa (pesado)

    try:
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl levanta vários tipos para arquivo inválido
        raise FileError("Não consegui abrir a planilha. Salve de novo como .xlsx.") from exc
    try:
        for sheet in workbook.worksheets:
            yield (
                (number, [_xlsx_cell(v) for v in values])
                for number, values in enumerate(sheet.iter_rows(values_only=True), start=1)
            )
    finally:
        workbook.close()


def _xlsx_cell(value: object) -> Cell:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, date):
        return value  # datetime também: a hora importa nos exports em UTC (Binance)
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # repr do float é a menor forma que volta ao mesmo número: 38.45, não 38.4499999.
        return Decimal(repr(value))
    if isinstance(value, Decimal):
        return value
    return str(value)


# csv --------------------------------------------------------------------------------


def _csv_sheets(content: bytes) -> Generator[Iterator[tuple[int, list[Cell]]]]:
    yield _csv_rows(content)


def _csv_rows(content: bytes) -> Iterator[tuple[int, list[Cell]]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252", errors="replace")
    first = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = max(";,\t", key=first.count)  # empate fica com o ponto e vírgula
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    for values in reader:
        yield reader.line_num, list(values)
