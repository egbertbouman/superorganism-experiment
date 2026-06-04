"""
IPV8 Liberation Community for announcing seeded content.

This community allows seedboxes to broadcast their torrents to the network,
enabling health checkers to discover and monitor them.
"""

import asyncio
import time
from dataclasses import dataclass
from hashlib import sha1
from typing import Callable, Dict, Optional

from ipv8.community import Community, CommunitySettings
from ipv8.lazy_community import lazy_wrapper
from ipv8.messaging.payload_dataclass import DataClassPayload
from ipv8.peer import Peer

from config import Config


@dataclass
class LiberatedContentPayload(DataClassPayload[1]):
    url: str
    license: str
    magnet_link: str
    timestamp: int  # Unix timestamp when content was liberated


@dataclass
class SeedboxInfoPayload(DataClassPayload[2]):
    friendly_name: str
    public_ip: str
    git_commit_hash: str
    uptime_seconds: int
    disk_total_bytes: int
    disk_used_bytes: int
    btc_address: str
    btc_balance_sat: int
    vps_provider_region: str
    vps_days_remaining: int


class LiberationCommunity(Community):
    """Seedboxes broadcast to this community; health checkers listen to discover torrents."""

    # Same community ID as SwarmHealth-Checker to enable discovery
    community_id = sha1(b"liberation_community").digest()

    def __init__(self, settings: CommunitySettings) -> None:
        super().__init__(settings)

        # Gossip dedup: btc_address -> unix timestamp of last forward
        self._last_forwarded_whoami: Dict[str, float] = {}

        self.on_content_received_callback: Optional[Callable[[Peer, LiberatedContentPayload], None]] = None
        self._on_new_peer_callback: Optional[Callable] = None
        self.on_seedbox_info_callback: Optional[Callable[[Peer, SeedboxInfoPayload], None]] = None

        self.add_message_handler(LiberatedContentPayload, self.on_liberated_content)
        self.add_message_handler(SeedboxInfoPayload, self.on_seedbox_info)

        self.logger.info("LiberationCommunity initialized (peer mid: %s)",
                        self.my_peer.mid.hex()[:16])

    def started(self) -> None:
        self.logger.info("LiberationCommunity started")

    def broadcast_content(self, payload: LiberatedContentPayload) -> int:
        peers = self.get_peers()
        if not peers:
            return 0
        sent = 0
        for peer in peers:
            try:
                self.ez_send(peer, payload)
                sent += 1
            except Exception as e:
                self.logger.warning("Failed to send to peer %s: %s", peer.mid.hex()[:16], e)
        return sent

    def set_new_peer_callback(self, callback: Callable) -> None:
        """Set callback invoked (as a coroutine) when a new peer connects."""
        self._on_new_peer_callback = callback

    def peer_added(self, peer: Peer) -> None:
        super().peer_added(peer)
        if self._on_new_peer_callback:
            asyncio.ensure_future(self._on_new_peer_callback(peer))

    @lazy_wrapper(LiberatedContentPayload)
    def on_liberated_content(self, peer: Peer, payload: LiberatedContentPayload) -> None:
        self.logger.info("Received content from peer %s: %s",
                        peer.mid.hex()[:16], payload.url[:60] if payload.url else "unknown")

        if self.on_content_received_callback:
            try:
                self.on_content_received_callback(peer, payload)
            except Exception as e:
                self.logger.error("Error in content received callback: %s", e)

    def set_content_received_callback(
        self,
        callback: Callable[[Peer, LiberatedContentPayload], None]
    ) -> None:
        self.on_content_received_callback = callback

    def broadcast_seedbox_info(self, payload: SeedboxInfoPayload) -> int:
        peers = self.get_peers()

        if not peers:
            self.logger.debug("No peers available to broadcast seedbox info to")
            return 0

        sent_count = 0
        for peer in peers:
            try:
                self.ez_send(peer, payload)
                sent_count += 1
            except Exception as e:
                self.logger.warning("Failed to send seedbox info to peer %s: %s",
                                   peer.mid.hex()[:16], e)

        if sent_count > 0:
            self.logger.info("Broadcasted seedbox info to %d peer(s)", sent_count)

        return sent_count

    @lazy_wrapper(SeedboxInfoPayload)
    def on_seedbox_info(self, peer: Peer, payload: SeedboxInfoPayload) -> None:
        if self.on_seedbox_info_callback:
            try:
                self.on_seedbox_info_callback(peer, payload)
            except Exception as e:
                self.logger.error("Error in seedbox info callback: %s", e)

        now = time.time()
        if now - self._last_forwarded_whoami.get(payload.btc_address, 0) > Config.WHOAMI_GOSSIP_COOLDOWN:
            self._last_forwarded_whoami[payload.btc_address] = now
            for other_peer in self.get_peers():
                if other_peer.mid != peer.mid:
                    try:
                        self.ez_send(other_peer, payload)
                    except Exception as e:
                        self.logger.warning("Failed to forward WHOAMI to %s: %s",
                                            other_peer.mid.hex()[:16], e)

    def set_seedbox_info_callback(
        self,
        callback: Callable[[Peer, SeedboxInfoPayload], None]
    ) -> None:
        self.on_seedbox_info_callback = callback
