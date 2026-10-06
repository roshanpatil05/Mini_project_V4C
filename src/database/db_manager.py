from __future__ import annotations

from threading import RLock
from typing import Any

import pymysql
import pymysql.cursors
from pymysql import Error as MySQLError

from src.config.settings import settings


class DatabaseConnection:
	"""Singleton owner for the application's MySQL connection."""

	_instances: dict[type, DatabaseConnection] = {}
	_instance_lock = RLock()

	def __new__(cls) -> DatabaseConnection:
		with cls._instance_lock:
			if cls not in cls._instances:
				cls._instances[cls] = super().__new__(cls)
		return cls._instances[cls]

	def __init__(self) -> None:
		if getattr(self, "_initialized", False):
			return
		self._connection = None
		self._connection_lock = RLock()
		self._initialized = True

	def _is_alive(self) -> bool:
		"""Check whether the current connection is usable."""
		if self._connection is None:
			return False
		try:
			self._connection.ping(reconnect=False)
			return True
		except Exception:
			return False

	def get_connection(self):
		with self._connection_lock:
			try:
				if not self._is_alive():
					self._connection = pymysql.connect(
						host=settings.host,
						port=settings.port,
						user=settings.user,
						password=settings.password,
						database=settings.database,
						cursorclass=pymysql.cursors.DictCursor,
					)
				return self._connection
			except MySQLError as exc:
				raise RuntimeError(f"Could not connect to MySQL: {exc}") from exc

	def execute(self, query: str, params: tuple[Any, ...] = (), commit: bool = False):
		connection = self.get_connection()
		cursor = connection.cursor()
		try:
			cursor.execute(query, params)
			if commit:
				connection.commit()
			return cursor
		except MySQLError as exc:
			connection.rollback()
			cursor.close()
			raise RuntimeError(f"Database operation failed: {exc}") from exc

	def fetch_all(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
		cursor = self.execute(query, params)
		try:
			return cursor.fetchall()
		finally:
			cursor.close()

	def fetch_one(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
		cursor = self.execute(query, params)
		try:
			return cursor.fetchone()
		finally:
			cursor.close()

	def close(self) -> None:
		with self._connection_lock:
			if self._connection is not None:
				try:
					self._connection.close()
				except Exception:
					pass
			self._connection = None

