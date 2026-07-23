import unittest

import discord

import karaoke
from karaoke import _move_entry_to_top


class KaraokeQueueTests(unittest.TestCase):
    def test_move_specific_queue_position_to_top(self):
        queue = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
            {"id": 3, "name": "Carol"},
        ]

        moved_entry = _move_entry_to_top(queue, 2)

        self.assertEqual(moved_entry["id"], 2)
        self.assertEqual([entry["id"] for entry in queue], [2, 1, 3])

    def test_bump_self_to_top_when_no_position_is_given(self):
        queue = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]

        _move_entry_to_top(queue, None, 3, "Carol")

        self.assertEqual([entry["id"] for entry in queue], [3, 1, 2])

    def test_queue_display_returns_embed_with_queue_entries(self):
        karaoke.karaoke_queues.clear()

        class DummyInteraction:
            guild_id = 1
            channel_id = 2

        interaction = DummyInteraction()
        queue = karaoke._get_queue(interaction)
        queue.extend([
            {"id": 10, "name": "Alice"},
            {"id": 20, "name": "Bob"},
        ])

        embed = karaoke._queue_display(interaction)

        self.assertIsInstance(embed, discord.Embed)
        self.assertIn("1. <@10>", embed.description)
        self.assertIn("2. <@20>", embed.description)


if __name__ == "__main__":
    unittest.main()
