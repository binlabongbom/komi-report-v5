"""Stable shared settings document, including past and future price dates.

Unlike the legacy setup response, this document never selects prices using the
receiver's current day. Local identities and credentials are excluded.
"""
from copy import deepcopy
from datetime import date
import math
import json

from services.secondary_setup import (
    SECONDARY_SETUP_CONTRACT, setup_snapshot_from_connection, validate_setup_snapshot,
)

PRICE_KEYS = ("a3_color", "a3_bw", "a4_color", "a4_bw")


def validate_price_history(rows):
    if not isinstance(rows, list):
        raise ValueError("Invalid price history")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"slot", "effective_date", *PRICE_KEYS}:
            raise ValueError("Invalid price history fields")
        if type(row["slot"]) is not int or row["slot"] not in range(3):
            raise ValueError("Invalid price slot")
        day = row["effective_date"]
        if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
            raise ValueError("Invalid price effective date")
        key = (row["slot"], day)
        if key in seen:
            raise ValueError("Duplicate price effective date")
        seen.add(key)
        for field in PRICE_KEYS:
            value = row[field]
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 9999:
                raise ValueError("Invalid price")
    if rows != sorted(rows, key=lambda row: (row["slot"], row["effective_date"])):
        raise ValueError("Price history must be sorted")


def from_connection(conn):
    snapshot = setup_snapshot_from_connection(conn)
    organization = snapshot["organization"]
    organization.pop("primary_installation_id")
    # A missing legacy start date must not manufacture a new revision daily.
    row = conn.execute("SELECT value FROM settings WHERE key='client_first_started_at'").fetchone()
    organization["first_started_at"] = row[0] if row else ""
    for device in snapshot["devices"]:
        device.pop("prices")
    columns = ("slot", "effective_date", *PRICE_KEYS)
    prices = [dict(zip(columns, row)) for row in conn.execute(
        "SELECT device_slot,effective_date,a3_color,a3_bw,a4_color,a4_bw "
        "FROM price_history ORDER BY device_slot,effective_date"
    )]
    payload = {"format_version": 2, "organization": organization,
               "settings": snapshot["settings"], "devices": snapshot["devices"],
               "price_history": prices}
    epochs = [{"slot": slot, "epoch_id": epoch_id} for slot, epoch_id in conn.execute(
        "SELECT device_slot,epoch_id FROM slot_meter_heads ORDER BY device_slot")]
    if epochs:
        payload.update(format_version=3, slot_epochs=epochs)
    validate(payload)
    return payload


def validate(payload):
    keys = {"format_version", "organization", "settings", "devices", "price_history"}
    if not isinstance(payload, dict) or type(payload.get("format_version")) is not int:
        raise ValueError("Invalid shared settings document")
    version = payload["format_version"]
    if version == 3:
        keys.add("slot_epochs")
        epochs = payload.get("slot_epochs")
        if (not isinstance(epochs, list) or not 1 <= len(epochs) <= 3
                or any(not isinstance(row, dict) or set(row) != {"slot", "epoch_id"}
                    or type(row["slot"]) is not int or row["slot"] not in range(3)
                    or not isinstance(row["epoch_id"], str) or len(row["epoch_id"]) != 64
                    or any(char not in "0123456789abcdef" for char in row["epoch_id"]) for row in epochs)
                or [row["slot"] for row in epochs] != sorted({row["slot"] for row in epochs})):
            raise ValueError("Invalid reviewed slot references")
    if version not in (2, 3) or set(payload) != keys:
        raise ValueError("Invalid shared settings document")
    legacy = deepcopy(payload)
    legacy.pop("slot_epochs", None)
    if (not isinstance(legacy["organization"], dict)
            or set(legacy["organization"]) != {"company_name", "first_started_at"}
            or not isinstance(legacy["devices"], list)
            or any(not isinstance(device, dict) for device in legacy["devices"])):
        raise ValueError("Invalid shared organization or devices")
    del legacy["format_version"]
    prices = legacy.pop("price_history")
    validate_price_history(prices)
    for device in legacy["devices"]:
        if "prices" in device:
            raise ValueError("Current-day prices cannot appear in shared history")
        device["prices"] = dict.fromkeys(PRICE_KEYS, 0.0)
    legacy["organization"]["primary_installation_id"] = ""
    normalized = validate_setup_snapshot({"contract": SECONDARY_SETUP_CONTRACT,
                                          "generated_at": "", **legacy})
    for device in normalized["devices"]:
        del device["prices"]
    del normalized["organization"]["primary_installation_id"]
    for key in ("organization", "settings", "devices"):
        if json.dumps(normalized[key], sort_keys=True, allow_nan=False) != json.dumps(payload[key], sort_keys=True, allow_nan=False):
            raise ValueError("Shared settings must be normalized")
