"""Prime Sale allocation estimation, in Decimal only.

The formula is the proportional rule from the Phase 4
specification:

    user allocation = (user commitment / total eligible
    commitment) x total token allocation

The result is an estimate, never a guarantee, and the
function refuses to run without verified inputs: a missing
or zero total commitment is an error, not a reason to
invent a total. Floats are never used for money here.
"""

from decimal import Decimal, InvalidOperation


def _to_decimal(value, field: str) -> Decimal:
    if value is None:
        raise ValueError(f"{field} is required for an allocation estimate")
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a valid number") from exc
    return result


def estimate_allocation(user_commitment, total_commitment, total_token_allocation) -> dict:
    """Estimate an allocation. Raises ValueError with a clear
    message when any input is missing, invalid, or when the
    total commitment is zero or negative."""
    user = _to_decimal(user_commitment, "user_commitment")
    total = _to_decimal(total_commitment, "total_commitment")
    allocation = _to_decimal(total_token_allocation, "total_token_allocation")
    if user <= 0:
        raise ValueError("user_commitment must be greater than zero")
    if total <= 0:
        raise ValueError("total_commitment must be greater than zero")
    if allocation <= 0:
        raise ValueError("total_token_allocation must be greater than zero")
    estimated = (user / total) * allocation
    return {
        "estimated_allocation": estimated,
        "user_commitment": user,
        "total_commitment": total,
        "total_token_allocation": allocation,
        "formula": "user_commitment / total_commitment * total_token_allocation",
        "is_estimate": True,
        "guarantee": "This is an estimate only, not a guaranteed allocation.",
    }
