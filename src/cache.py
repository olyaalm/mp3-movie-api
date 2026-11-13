"""Cache movie retrieval responses in an isolated in-memory Redis client."""

import json
import logging

import fakeredis


logger = logging.getLogger(__name__)


class MovieCache:
    """Store movie list responses by requested row limit."""

    def __init__(self):
        """Create a dedicated in-memory cache for movie responses."""
        self.client = fakeredis.FakeRedis(decode_responses=True)

    def make_key(self, limit):
        """Return the cache key for a movie retrieval limit."""
        return f"movies:limit:{limit}"

    def get(self, limit):
        """Return the cached response dictionary, or None when it is absent."""
        key = self.make_key(limit)
        cached_response = self.client.get(key)
        if cached_response is None:
            logger.debug("Cache MISS: %s", key)
            return None

        logger.debug("Cache HIT: %s", key)
        return json.loads(cached_response)

    def set(self, limit, response):
        """Cache a response dictionary for 90 seconds."""
        key = self.make_key(limit)
        self.client.set(key, json.dumps(response), ex=90)

    def invalidate(self):
        """Remove all cached movie retrievals from this dedicated client."""
        self.client.flushall()
        logger.debug("Invalidated movie cache")