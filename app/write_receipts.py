"""Retry a POST without repeating its write, including when the first success reply was lost.

Call after request validation/authentication and before other database work. The receipt and
write must share this connection and :meth:`WriteReceipt.commit`; no intermediate commit is safe.
Requests without a key retain the ordinary one-write-per-call behavior.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import Header, HTTPException
from pydantic import BaseModel

from .db import utcnow

RESPONSE_TTL = timedelta(hours=24)
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]
KEY_PATTERN = re.compile(r"[A-Za-z0-9._:-]{8,128}\Z", re.ASCII)
KEY_ERROR = "Idempotency-Key must be 8 to 128 letters, digits, dots, underscores, colons or hyphens"
CHANGED_ERROR = "This save key was already used for different data. Start a new save for the changed data."
EXPIRED_ERROR = "This save was already handled, but its reply is no longer available. Check your log before starting a new save."


class WriteReceipt:
    def __init__(self, conn: sqlite3.Connection, user_id: int, operation: str, key: str | None,
                 body: BaseModel | dict[str, Any]) -> None:
        self.conn, self.user_id, self.operation, self.key = conn, user_id, operation, key
        self.replay: dict[str, Any] | None = None
        self.body_hash: str | None = None
        if key is None:
            return
        if not KEY_PATTERN.fullmatch(key):
            raise HTTPException(status_code=400, detail=KEY_ERROR)
        payload = body.model_dump(mode="json") if isinstance(body, BaseModel) else body
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self.body_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        # Reserve the writer before looking up the key. A concurrent identical POST waits until
        # the first write+receipt commit, then sees its receipt rather than creating another row.
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        cutoff = (datetime.now(timezone.utc) - RESPONSE_TTL).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        conn.execute("UPDATE write_receipts SET response_json = NULL WHERE user_id = ? AND response_json IS NOT NULL AND created_at <= ?", (user_id, cutoff))
        row = conn.execute(
            "SELECT body_hash, response_json FROM write_receipts WHERE user_id = ? AND operation = ? AND request_key = ?",
            (user_id, operation, key),
        ).fetchone()
        if row is None:
            return
        if row[0] != self.body_hash:
            conn.commit()
            raise HTTPException(status_code=409, detail=CHANGED_ERROR)
        if row[1] is None:
            conn.commit()
            raise HTTPException(status_code=409, detail=EXPIRED_ERROR)
        self.replay = json.loads(row[1])
        conn.commit()

    def commit(self, result: dict[str, Any], model: type[BaseModel]) -> dict[str, Any]:
        """Validate the cached result before committing either it or the underlying write."""
        if self.key is not None:
            response = model.model_validate(result).model_dump(mode="json")
            self.conn.execute(
                "INSERT INTO write_receipts (user_id, operation, request_key, body_hash, response_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (self.user_id, self.operation, self.key, self.body_hash,
                 json.dumps(response, ensure_ascii=False, separators=(",", ":"), allow_nan=False), utcnow()),
            )
        self.conn.commit()
        return result
