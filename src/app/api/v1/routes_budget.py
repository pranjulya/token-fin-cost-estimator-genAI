"""Budget admin routes (PRD # 28)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import budget_repo_dep
from app.core.exceptions import InvalidRequestError
from app.repositories.budget_repository import BudgetRepository
from app.schemas.budget import BudgetCreate, BudgetOut, BudgetUpdate

router = APIRouter(prefix="/budgets", tags=["budget"])


async def _get_or_404(repo: BudgetRepository, budget_id: int):
    budget = await repo.get(budget_id)
    if budget is None:
        raise HTTPException(status_code=404, detail="budget not found")
    return budget


@router.post("", response_model=BudgetOut, status_code=201)
async def create_budget(
    body: BudgetCreate, repo: BudgetRepository = Depends(budget_repo_dep)
) -> BudgetOut:
    row = await repo.create(
        scope_type=body.scope_type,
        scope_id=body.scope_id,
        period_type=body.period_type,
        limit_amount=body.limit_amount,
        currency=body.currency,
        warning_threshold=body.warning_threshold,
        critical_threshold=body.critical_threshold,
        enforcement_mode=body.enforcement_mode,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
    )
    return BudgetOut.model_validate(row)


@router.get("/{budget_id}", response_model=BudgetOut)
async def get_budget(
    budget_id: int, repo: BudgetRepository = Depends(budget_repo_dep)
) -> BudgetOut:
    return BudgetOut.model_validate(await _get_or_404(repo, budget_id))


@router.patch("/{budget_id}", response_model=BudgetOut)
async def update_budget(
    budget_id: int,
    body: BudgetUpdate,
    repo: BudgetRepository = Depends(budget_repo_dep),
) -> BudgetOut:
    budget = await _get_or_404(repo, budget_id)
    if body.warning_threshold is not None and body.critical_threshold is not None:
        if body.warning_threshold > body.critical_threshold:
            raise InvalidRequestError("warning_threshold must be <= critical_threshold")
    row = await repo.update(
        budget,
        limit_amount=body.limit_amount,
        warning_threshold=body.warning_threshold,
        critical_threshold=body.critical_threshold,
        enforcement_mode=body.enforcement_mode,
        ends_at=body.ends_at,
    )
    return BudgetOut.model_validate(row)
