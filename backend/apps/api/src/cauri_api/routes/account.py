"""Dados da conta e administração da allowlist (só admin)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from cauri_api.schemas import AllowlistEntryIn, AllowlistEntryOut, AllowlistPatchIn, MeOut
from cauri_api.session import SessionDep

router = APIRouter(tags=["account"])


@router.get("/v1/me", response_model=MeOut)
def me(session: SessionDep) -> MeOut:
    with session.member() as conn:
        row = conn.execute(
            "select p.display_name, app.current_role_name() as role"
            " from app.profiles p where p.user_id = %s",
            [session.user.id],
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Perfil não encontrado.")
    return MeOut(
        user_id=session.user.id,
        email=session.user.email,
        display_name=row["display_name"],
        role=row["role"],
    )


@router.get("/v1/admin/allowlist", response_model=list[AllowlistEntryOut])
def list_allowlist(session: SessionDep) -> list[AllowlistEntryOut]:
    with session.admin() as conn:
        rows = conn.execute(
            "select email, role, note, added_at from app.allowlist order by added_at"
        ).fetchall()
    return [AllowlistEntryOut(**r) for r in rows]


@router.post(
    "/v1/admin/allowlist", response_model=AllowlistEntryOut, status_code=status.HTTP_201_CREATED
)
def add_allowlist(body: AllowlistEntryIn, session: SessionDep) -> AllowlistEntryOut:
    with session.admin() as conn:
        row = conn.execute(
            "insert into app.allowlist (email, role, note, added_by) values (lower(%s), %s, %s, %s)"
            " on conflict (email) do nothing returning email, role, note, added_at",
            [body.email, body.role, body.note, session.user.id],
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Esse e-mail já está na lista.")
    return AllowlistEntryOut(**row)


@router.patch("/v1/admin/allowlist/{email}", response_model=AllowlistEntryOut)
def update_allowlist(email: str, body: AllowlistPatchIn, session: SessionDep) -> AllowlistEntryOut:
    with session.admin() as conn:
        row = conn.execute(
            "update app.allowlist set role = coalesce(%s, role), note = coalesce(%s, note)"
            " where email = lower(%s) returning email, role, note, added_at",
            [body.role, body.note, email],
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "E-mail não está na lista.")
    return AllowlistEntryOut(**row)


@router.delete("/v1/admin/allowlist/{email}", status_code=status.HTTP_204_NO_CONTENT)
def remove_allowlist(email: str, session: SessionDep) -> None:
    """Tira o acesso na hora: as policies checam a allowlist a cada consulta."""
    with session.admin() as conn:
        row = conn.execute(
            "delete from app.allowlist where email = lower(%s) returning email", [email]
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "E-mail não está na lista.")
