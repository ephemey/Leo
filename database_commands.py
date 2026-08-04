import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

import discord
from discord import app_commands

logger = logging.getLogger(__name__)


class DatabaseEditError(ValueError):
    """Raised when a requested database edit is invalid or unsafe."""


@dataclass(frozen=True)
class DatabaseEditResult:
    action: str
    database: str
    table: str
    field: str | None = None
    old_value: Any = None
    new_value: Any = None

    def format_message(self) -> str:
        location = f"`{self.database}.{self.table}`"
        if self.action == "insert":
            return f"✅ Inserted one record into {location}."
        if self.action == "delete":
            return f"✅ Deleted one record from {location}."
        return (
            f"✅ Updated `{self.field}` in {location}: "
            f"`{self.old_value}` → `{self.new_value}`."
        )


class DatabaseEditor:
    """Schema-validated editor for the bot's two SQLite databases."""

    def __init__(self, chengyu_game, karaoke_points):
        self._databases = {
            "chengyu": chengyu_game,
            "karaoke": karaoke_points,
        }

    def list_tables(self, database: str) -> list[str]:
        target = self._get_target(database)
        rows = target.conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
        return [row[0] for row in rows]

    def list_fields(self, database: str, table: str) -> list[str]:
        if table not in self.list_tables(database):
            return []
        return list(self._get_schema(self._get_target(database).conn, table))

    def edit(
        self,
        database: str,
        table: str,
        action: str,
        record: str | None = None,
        field: str | None = None,
        value: str | None = None,
        *,
        guild_id: int,
        user_id: int | None = None,
        username: str | None = None,
    ) -> DatabaseEditResult:
        target = self._get_target(database)
        action = action.lower().strip()
        if action not in {"set", "add", "deduct", "insert", "delete"}:
            raise DatabaseEditError(f"Unsupported action: {action}")

        with target._lock:
            tables = self._list_tables_locked(target.conn)
            if table not in tables:
                raise DatabaseEditError(
                    f"Unknown table `{table}` for the {database} database."
                )

            schema = self._get_schema(target.conn, table)
            if "guild_id" not in schema:
                raise DatabaseEditError(
                    f"`{table}` is not server-scoped and cannot be edited with this command."
                )

            record_values = self._parse_record(record) if record else {}
            if "guild_id" in record_values:
                raise DatabaseEditError(
                    "Do not include `guild_id`; the current server is selected automatically."
                )
            record_values["guild_id"] = guild_id

            if user_id is not None:
                if "user_id" not in schema:
                    raise DatabaseEditError(
                        f"`{table}` does not contain user records; omit the `user` option."
                    )
                if "user_id" in record_values:
                    raise DatabaseEditError(
                        "Specify the user with the `user` option, not in `record`."
                    )
                record_values["user_id"] = user_id
                if (
                    action == "insert"
                    and "username" in schema
                    and "username" not in record_values
                    and username is not None
                ):
                    record_values["username"] = username

            converted_record = self._validate_and_convert_record(record_values, schema)

            try:
                if action == "insert":
                    return self._insert(
                        target.conn,
                        database,
                        table,
                        schema,
                        converted_record,
                        field,
                        value,
                    )

                if action == "delete":
                    if field is not None or value is not None:
                        raise DatabaseEditError(
                            "Do not provide `field` or `value` for a delete action."
                        )
                    return self._delete(
                        target.conn,
                        database,
                        table,
                        converted_record,
                    )

                if not field or value is None:
                    raise DatabaseEditError(
                        f"The `{action}` action requires both `field` and `value`."
                    )
                if field not in schema:
                    raise DatabaseEditError(f"Unknown field `{field}` in `{table}`.")
                if field == "guild_id":
                    raise DatabaseEditError(
                        "`guild_id` cannot be edited; `/dbedit` is always scoped to this server."
                    )

                return self._update(
                    target.conn,
                    database,
                    table,
                    action,
                    converted_record,
                    field,
                    value,
                    schema,
                )
            except sqlite3.Error as error:
                target.conn.rollback()
                raise DatabaseEditError(f"SQLite rejected the edit: {error}") from error

    def _get_target(self, database: str):
        try:
            return self._databases[database.lower().strip()]
        except KeyError as error:
            raise DatabaseEditError(
                "Database must be either `chengyu` or `karaoke`."
            ) from error

    @staticmethod
    def _list_tables_locked(conn: sqlite3.Connection) -> list[str]:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return [row[0] for row in rows]

    @staticmethod
    def _quote(identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    def _get_schema(self, conn: sqlite3.Connection, table: str) -> dict[str, dict]:
        rows = conn.execute(f"PRAGMA table_info({self._quote(table)})").fetchall()
        return {
            row[1]: {
                "type": (row[2] or "TEXT").upper(),
                "not_null": bool(row[3]),
                "primary_key": bool(row[5]),
            }
            for row in rows
        }

    @staticmethod
    def _parse_record(record: str) -> dict[str, Any]:
        record = record.strip()
        if not record:
            raise DatabaseEditError("The record selector cannot be empty.")

        if record.startswith("{"):
            try:
                parsed = json.loads(record)
            except json.JSONDecodeError as error:
                raise DatabaseEditError(f"Invalid record JSON: {error.msg}.") from error
            if not isinstance(parsed, dict) or not parsed:
                raise DatabaseEditError("Record JSON must be a non-empty object.")
            return parsed

        parsed = {}
        for assignment in record.split(","):
            if "=" not in assignment:
                raise DatabaseEditError(
                    "Record selectors must use `field=value`, separated by commas."
                )
            key, raw_value = assignment.split("=", 1)
            key = key.strip()
            if not key:
                raise DatabaseEditError("A record selector contains an empty field name.")
            if key in parsed:
                raise DatabaseEditError(f"Duplicate record field `{key}`.")
            parsed[key] = raw_value.strip()
        return parsed

    def _validate_and_convert_record(
        self,
        record: dict[str, Any],
        schema: dict[str, dict],
    ) -> dict[str, Any]:
        converted = {}
        for field, value in record.items():
            if field not in schema:
                raise DatabaseEditError(f"Unknown record field `{field}`.")
            converted[field] = self._convert_value(value, schema[field])
        return converted

    @staticmethod
    def _convert_value(value: Any, column: dict) -> Any:
        if value is None or (isinstance(value, str) and value.lower() == "null"):
            if column["not_null"] or column["primary_key"]:
                raise DatabaseEditError("A required field cannot be set to NULL.")
            return None

        column_type = column["type"]
        if "INT" in column_type:
            if isinstance(value, str):
                mention = re.fullmatch(r"<@!?(\d+)>", value.strip())
                value = mention.group(1) if mention else value.strip()
            try:
                return int(value)
            except (TypeError, ValueError) as error:
                raise DatabaseEditError(f"`{value}` is not a valid integer.") from error

        if any(kind in column_type for kind in ("REAL", "FLOAT", "DOUBLE")):
            try:
                return float(value)
            except (TypeError, ValueError) as error:
                raise DatabaseEditError(f"`{value}` is not a valid number.") from error

        return str(value)

    def _where_clause(self, record: dict[str, Any]) -> tuple[str, list[Any]]:
        clauses = []
        parameters = []
        for field, value in record.items():
            quoted = self._quote(field)
            if value is None:
                clauses.append(f"{quoted} IS NULL")
            else:
                clauses.append(f"{quoted} = ?")
                parameters.append(value)
        return " AND ".join(clauses), parameters

    def _find_one(
        self,
        conn: sqlite3.Connection,
        table: str,
        record: dict[str, Any],
        field: str,
    ) -> Any:
        where, parameters = self._where_clause(record)
        rows = conn.execute(
            f"SELECT {self._quote(field)} FROM {self._quote(table)} "
            f"WHERE {where} LIMIT 2",
            parameters,
        ).fetchall()
        if not rows:
            raise DatabaseEditError("No record matched that selector.")
        if len(rows) > 1:
            raise DatabaseEditError(
                "That selector matched multiple records; include more key fields."
            )
        return rows[0][0]

    def _update(
        self,
        conn: sqlite3.Connection,
        database: str,
        table: str,
        action: str,
        record: dict[str, Any],
        field: str,
        raw_value: str,
        schema: dict[str, dict],
    ) -> DatabaseEditResult:
        old_value = self._find_one(conn, table, record, field)
        converted_value = self._convert_value(raw_value, schema[field])

        if action in {"add", "deduct"}:
            if not isinstance(old_value, (int, float)) or not isinstance(
                converted_value, (int, float)
            ):
                raise DatabaseEditError("Add and deduct actions require a numeric field.")
            if converted_value < 0:
                raise DatabaseEditError("Add and deduct amounts cannot be negative.")
            direction = 1 if action == "add" else -1
            new_value = max(0, old_value + direction * converted_value)
        else:
            new_value = converted_value

        where, parameters = self._where_clause(record)
        conn.execute(
            f"UPDATE {self._quote(table)} SET {self._quote(field)} = ? "
            f"WHERE {where}",
            [new_value, *parameters],
        )
        conn.commit()
        logger.info(
            "Database edit: database=%s table=%s action=%s field=%s",
            database,
            table,
            action,
            field,
        )
        return DatabaseEditResult(
            action=action,
            database=database,
            table=table,
            field=field,
            old_value=old_value,
            new_value=new_value,
        )

    def _insert(
        self,
        conn: sqlite3.Connection,
        database: str,
        table: str,
        schema: dict[str, dict],
        record: dict[str, Any],
        field: str | None,
        value: str | None,
    ) -> DatabaseEditResult:
        insert_values = dict(record)
        if (field is None) != (value is None):
            raise DatabaseEditError(
                "For an insert, provide both `field` and `value`, or omit both."
            )
        if field is not None:
            if field not in schema:
                raise DatabaseEditError(f"Unknown field `{field}` in `{table}`.")
            if field in insert_values:
                raise DatabaseEditError(
                    f"`{field}` is already present in the record values."
                )
            insert_values[field] = self._convert_value(value, schema[field])

        columns = ", ".join(self._quote(column) for column in insert_values)
        placeholders = ", ".join("?" for _ in insert_values)
        conn.execute(
            f"INSERT INTO {self._quote(table)} ({columns}) VALUES ({placeholders})",
            list(insert_values.values()),
        )
        conn.commit()
        logger.info("Database edit: database=%s table=%s action=insert", database, table)
        return DatabaseEditResult(action="insert", database=database, table=table)

    def _delete(
        self,
        conn: sqlite3.Connection,
        database: str,
        table: str,
        record: dict[str, Any],
    ) -> DatabaseEditResult:
        first_field = next(iter(record))
        self._find_one(conn, table, record, first_field)
        where, parameters = self._where_clause(record)
        conn.execute(
            f"DELETE FROM {self._quote(table)} WHERE {where}",
            parameters,
        )
        conn.commit()
        logger.info("Database edit: database=%s table=%s action=delete", database, table)
        return DatabaseEditResult(action="delete", database=database, table=table)


async def _is_owner(interaction: discord.Interaction) -> bool:
    return await interaction.client.is_owner(interaction.user)


def setup(bot, chengyu_game, karaoke_points) -> DatabaseEditor:
    editor = DatabaseEditor(chengyu_game, karaoke_points)

    @bot.tree.command(name="dbedit", description="Edit bot database records (bot owner only)")
    @app_commands.describe(
        database="Database to edit",
        table="Table name",
        action="Edit operation",
        user="User whose record should be edited",
        record="Additional selector/values, e.g. channel_id=123",
        field="Field to update (not used for delete; optional for insert)",
        value="New value or numeric amount (not used for delete)",
    )
    @app_commands.choices(
        database=[
            app_commands.Choice(name="Chengyu", value="chengyu"),
            app_commands.Choice(name="Karaoke", value="karaoke"),
        ],
        action=[
            app_commands.Choice(name="Set", value="set"),
            app_commands.Choice(name="Add", value="add"),
            app_commands.Choice(name="Deduct", value="deduct"),
            app_commands.Choice(name="Insert", value="insert"),
            app_commands.Choice(name="Delete", value="delete"),
        ],
    )
    @app_commands.guild_only()
    @app_commands.check(_is_owner)
    async def dbedit(
        interaction: discord.Interaction,
        database: str,
        table: str,
        action: str,
        user: discord.Member | None = None,
        record: str | None = None,
        field: str | None = None,
        value: str | None = None,
    ):
        logger.info(
            "/dbedit called by %s: database=%s table=%s action=%s field=%s",
            interaction.user,
            database,
            table,
            action,
            field,
        )
        try:
            result = editor.edit(
                database,
                table,
                action,
                record,
                field,
                value,
                guild_id=interaction.guild_id,
                user_id=user.id if user else None,
                username=(user.display_name or user.name) if user else None,
            )
        except DatabaseEditError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return

        await interaction.response.send_message(result.format_message(), ephemeral=True)

    @dbedit.autocomplete("table")
    async def dbedit_table_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        database = getattr(interaction.namespace, "database", None)
        if database not in {"chengyu", "karaoke"}:
            return []
        current = current.lower()
        return [
            app_commands.Choice(name=table, value=table)
            for table in editor.list_tables(database)
            if current in table.lower()
        ][:25]

    @dbedit.autocomplete("field")
    async def dbedit_field_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        database = getattr(interaction.namespace, "database", None)
        table = getattr(interaction.namespace, "table", None)
        if database not in {"chengyu", "karaoke"} or not table:
            return []
        current = current.lower()
        return [
            app_commands.Choice(name=field, value=field)
            for field in editor.list_fields(database, table)
            if current in field.lower()
        ][:25]

    return editor
