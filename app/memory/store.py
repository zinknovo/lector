"""Minimal async preference store used by the main agent loop."""

from pydantic import BaseModel


class Preference(BaseModel):
    text: str


class PreferenceStore:
    """Process-local store; replace with a persistent backend in production."""

    def __init__(self) -> None:
        self._items: dict[str, list[Preference]] = {}

    async def read_relevant(
        self, user_id: str, query: str, limit: int = 20
    ) -> list[Preference]:
        del query
        return list(self._items.get(user_id, []))[-limit:]

    async def write_many(self, user_id: str, texts: list[str]) -> None:
        items = self._items.setdefault(user_id, [])
        known = {item.text for item in items}
        for text in texts:
            normalized = text.strip()
            if normalized and normalized not in known:
                items.append(Preference(text=normalized))
                known.add(normalized)


store = PreferenceStore()

