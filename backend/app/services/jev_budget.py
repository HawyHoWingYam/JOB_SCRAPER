from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.jev import JevBudgetReservation, JevRuntimeSettings
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService
from app.utils.time import utc_now


class JevBudgetExhaustedError(RuntimeError):
    def __init__(self, *, remaining_microdollars: int) -> None:
        super().__init__("Jev allowance is exhausted")
        self.remaining_microdollars = remaining_microdollars


class JevBudgetLedger:
    """Own atomic reservations and settlement for one cumulative allowance."""

    def __init__(self, db: Session, *, scope: str = "online") -> None:
        if scope not in {"online", "maintenance"}:
            raise ValueError("unknown Jev budget scope")
        self.db = db
        self.scope = scope

    def reserve(
        self,
        *,
        attempt_key: str,
        microdollars: int,
    ) -> JevBudgetReservation:
        if not attempt_key.strip():
            raise ValueError("attempt_key must not be blank")
        if microdollars <= 0:
            raise ValueError("reservation must be positive")
        existing = self.db.scalar(
            select(JevBudgetReservation).where(
                JevBudgetReservation.attempt_key == attempt_key
            )
        )
        if existing is not None:
            if (
                existing.reserved_microdollars != microdollars
                or existing.budget_scope != self.scope
            ):
                raise ValueError("attempt_key already has a different reservation")
            return existing

        JevRuntimeSettingsService(self.db).get_or_create()
        allowance_field, spent_field, reserved_field = self._fields()
        statement = (
            update(JevRuntimeSettings)
            .where(
                JevRuntimeSettings.id == 1,
                spent_field + reserved_field + microdollars <= allowance_field,
            )
            .values({reserved_field.key: reserved_field + microdollars})
        )
        result = self.db.execute(statement)
        if result.rowcount != 1:
            self.db.expire_all()
            remaining = self.snapshot()["remaining_microdollars"]
            raise JevBudgetExhaustedError(remaining_microdollars=remaining)
        reservation = JevBudgetReservation(
            settings_id=1,
            attempt_key=attempt_key,
            budget_scope=self.scope,
            status="reserved",
            reserved_microdollars=microdollars,
        )
        self.db.add(reservation)
        self.db.flush()
        return reservation

    def settle(
        self,
        reservation_id: str,
        *,
        actual_microdollars: int,
    ) -> JevBudgetReservation:
        reservation = self.db.scalar(
            select(JevBudgetReservation)
            .where(JevBudgetReservation.id == reservation_id)
            .with_for_update()
        )
        if reservation is None:
            raise KeyError(reservation_id)
        self._require_scope(reservation)
        if reservation.status == "settled":
            if reservation.actual_microdollars != actual_microdollars:
                raise ValueError("reservation is already settled with another amount")
            return reservation
        if reservation.status != "reserved":
            raise ValueError("only a reserved charge can be settled")
        if not 0 <= actual_microdollars <= reservation.reserved_microdollars:
            raise ValueError("actual charge must fit within the reservation")

        _allowance_field, spent_field, reserved_field = self._fields()
        result = self.db.execute(
            update(JevRuntimeSettings)
            .where(
                JevRuntimeSettings.id == reservation.settings_id,
                reserved_field >= reservation.reserved_microdollars,
            )
            .values(
                {
                    reserved_field.key: (
                        reserved_field - reservation.reserved_microdollars
                    ),
                    spent_field.key: spent_field + actual_microdollars,
                }
            )
        )
        if result.rowcount != 1:
            raise RuntimeError("Jev allowance accounting is inconsistent")
        reservation.status = "settled"
        reservation.actual_microdollars = actual_microdollars
        reservation.settled_at = utc_now()
        self.db.flush()
        self.db.expire_all()
        return self.get_reservation(reservation_id)

    def get_reservation(self, reservation_id: str) -> JevBudgetReservation:
        reservation = self.db.get(JevBudgetReservation, reservation_id)
        if reservation is None:
            raise KeyError(reservation_id)
        return reservation

    def mark_uncertain(self, reservation_id: str) -> JevBudgetReservation:
        reservation = self._locked_reservation(reservation_id)
        self._require_scope(reservation)
        if reservation.status == "uncertain":
            return reservation
        if reservation.status != "reserved":
            raise ValueError("only a reserved charge can become uncertain")
        reservation.status = "uncertain"
        self.db.flush()
        return reservation

    def release(self, reservation_id: str) -> JevBudgetReservation:
        reservation = self._locked_reservation(reservation_id)
        self._require_scope(reservation)
        if reservation.status == "released":
            return reservation
        if reservation.status != "reserved":
            raise ValueError(f"a {reservation.status} charge cannot be released")
        _allowance_field, _spent_field, reserved_field = self._fields()
        result = self.db.execute(
            update(JevRuntimeSettings)
            .where(
                JevRuntimeSettings.id == reservation.settings_id,
                reserved_field >= reservation.reserved_microdollars,
            )
            .values(
                {
                    reserved_field.key: (
                        reserved_field - reservation.reserved_microdollars
                    )
                }
            )
        )
        if result.rowcount != 1:
            raise RuntimeError("Jev allowance accounting is inconsistent")
        reservation.status = "released"
        reservation.actual_microdollars = 0
        reservation.settled_at = utc_now()
        self.db.flush()
        self.db.expire_all()
        return self.get_reservation(reservation_id)

    def _locked_reservation(self, reservation_id: str) -> JevBudgetReservation:
        reservation = self.db.scalar(
            select(JevBudgetReservation)
            .where(JevBudgetReservation.id == reservation_id)
            .with_for_update()
        )
        if reservation is None:
            raise KeyError(reservation_id)
        return reservation

    def snapshot(self) -> dict[str, int]:
        row = JevRuntimeSettingsService(self.db).get_or_create()
        prefix = "maintenance_" if self.scope == "maintenance" else ""
        allowance = int(getattr(row, f"{prefix}allowance_microdollars"))
        spent = int(getattr(row, f"{prefix}spent_microdollars"))
        reserved = int(getattr(row, f"{prefix}reserved_microdollars"))
        return {
            "allowance_microdollars": allowance,
            "spent_microdollars": spent,
            "reserved_microdollars": reserved,
            "remaining_microdollars": max(0, allowance - spent - reserved),
        }

    def _fields(self):
        if self.scope == "maintenance":
            return (
                JevRuntimeSettings.maintenance_allowance_microdollars,
                JevRuntimeSettings.maintenance_spent_microdollars,
                JevRuntimeSettings.maintenance_reserved_microdollars,
            )
        return (
            JevRuntimeSettings.allowance_microdollars,
            JevRuntimeSettings.spent_microdollars,
            JevRuntimeSettings.reserved_microdollars,
        )

    def _require_scope(self, reservation: JevBudgetReservation) -> None:
        if reservation.budget_scope != self.scope:
            raise ValueError("reservation belongs to another Jev budget scope")


__all__ = ["JevBudgetExhaustedError", "JevBudgetLedger"]
