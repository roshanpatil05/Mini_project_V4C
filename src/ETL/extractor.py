from __future__ import annotations

from pathlib import Path

import pandas as pd


class CSVExtractor:
	"""Read synthesized source data while parsing its date columns."""

	def extract(self, path: str | Path) -> pd.DataFrame:
		frame = pd.read_csv(path)
		for column in ("hire_date", "start_date", "end_date", "review_date", "assigned_date"):
			if column in frame.columns:
				frame[column] = pd.to_datetime(frame[column], errors="coerce")
		return frame
