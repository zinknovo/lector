import asyncio

from app.memory.store import PreferenceStore


def test_preference_store_writes_and_reads_user_preferences() -> None:
    async def run():
        store = PreferenceStore()
        await store.write_many("u1", ["不要塑料", "偏好小众"])
        return await store.read_relevant("u1", "旅行背包")

    result = asyncio.run(run())
    assert [item.text for item in result] == ["不要塑料", "偏好小众"]

