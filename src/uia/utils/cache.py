"""Page cache utility for incremental scraping.

Provides the PageCache class that tracks hashes of cleaned page contents
to skip redundant extraction when contents have not changed.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional

class PageCache:
    """A JSON-backed cache of page text hashes for incremental runs."""

    def __init__(self, cache_path: str = "data/raw_cache/page_hashes.json"):
        self.cache_path = cache_path
        self.cache: Dict[str, Dict[str, str]] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        """Loads cached hashes from the JSON file if it exists."""
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
            except Exception:
                self.cache = {}
        else:
            self.cache = {}

    def _save_cache(self) -> None:
        """Saves current cache entries to the JSON file."""
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2)
        except Exception:
            pass

    def _compute_hash(self, text: str) -> str:
        """Computes the SHA-256 hash of the given clean text."""
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    def has_changed(self, url: str, clean_text: str) -> bool:
        """Compares clean_text hash with the stored hash for url.

        Returns:
            True if the text is different or url is not cached, False otherwise.
        """
        if url not in self.cache:
            return True
        stored_hash = self.cache[url].get("hash")
        current_hash = self._compute_hash(clean_text)
        return stored_hash != current_hash

    def update(self, url: str, clean_text: str) -> None:
        """Stores the hash and ISO timestamp for the given url."""
        current_hash = self._compute_hash(clean_text)
        iso_timestamp = datetime.now(timezone.utc).isoformat()
        self.cache[url] = {
            "hash": current_hash,
            "fetched_at": iso_timestamp
        }
        self._save_cache()
