"""
Holodex API integration for OtomoPy.
"""

import asyncio
import json
import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import aiohttp

from otomopy.channel_cache import ChannelCache

logger = logging.getLogger(__name__)


class HolodexAPI:
    """Client for interacting with the Holodex API."""

    BASE_URL = "https://holodex.net/api/v2"

    def __init__(self, api_key: str):
        """Initialize the Holodex API client.

        Args:
            api_key: Holodex API key
        """
        self.api_key = api_key
        self.session: aiohttp.ClientSession | None = None
        self._channel_cache = None
        self._last_cache_refresh = 0  # Unix timestamp of last cache refresh

    async def initialize(self):
        """Initialize the API client session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers={"X-APIKEY": self.api_key})

    async def close(self):
        """Close the API client session."""
        if self.session and not self.session.closed:
            await self.session.close()

    async def get_live_streams(self, channel_ids: set[str]) -> list[dict[str, Any]] | None:
        """Get live streams for the specified channels.

        Args:
            channel_ids: Set of YouTube channel IDs to check

        Returns:
            List of live stream data
        """
        await self.initialize()

        if not channel_ids:
            logger.debug("No channel IDs provided to get_live_streams")
            return None

        try:
            # Use the /users/live endpoint which is more efficient for our use case
            params = {
                "channels": ",".join(channel_ids),
            }

            logger.debug(f"get_live_streams API call with params: {params}")
            logger.debug(f"Checking channels: {list(channel_ids)}")

            if self.session is None:
                logger.error("Session is None in get_live_streams")
                return None

            url = f"{self.BASE_URL}/users/live"
            logger.debug(f"Making request to: {url}")

            async with self.session.get(url, params=params) as response:
                logger.debug(f"Response status: {response.status}")
                logger.debug(f"Response headers: {dict(response.headers)}")

                if response.status == 200:
                    data = await response.json()
                    logger.debug(f"Response data type: {type(data)}")
                    logger.debug(f"Response data length: {len(data) if data else 0}")

                    if data:
                        logger.info(f"Found {len(data)} live/upcoming streams")
                    else:
                        logger.info("No live/upcoming streams found in API response")

                    return data if data else None
                else:
                    response_text = await response.text()
                    logger.error(f"Error fetching live streams: {response.status}")
                    logger.error(f"Response text: {response_text[:500]}...")  # First 500 chars
                    return None
        except Exception:
            logger.exception("Exception fetching live streams:")
            return None

    async def get_channel_info(self, channel_id: str) -> dict[str, Any] | None:
        """Get information about a specific channel.

        Args:
            channel_id: YouTube channel ID

        Returns:
            Channel information or None if not found
        """
        await self.initialize()

        try:
            if self.session is None:
                logger.error("Session is None in get_channel_info")
                return None

            async with self.session.get(f"{self.BASE_URL}/channels/{channel_id}") as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.error(f"Error fetching channel info: {response.status}")
                    return None
        except Exception:
            logger.exception("Exception fetching channel info:")
            return None

    async def get_all_channels(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get all VTuber channels from Holodex.

        This method fetches VTuber channels from Holodex API.
        Args:
            limit: Maximum number of channels to return per request

        Returns:
            List of VTuber channel data
        """
        await self.initialize()

        try:
            if self.session is None:
                logger.error("Session is None in get_all_channels")
                return []

            # Add rate limiting to avoid 429 errors
            request_delay = 0.5  # 500 ms delay between requests

            all_channels = []

            # Define a maximum number of API calls to avoid excessive rate limiting
            max_api_calls = 100
            api_call_count = 0

            logger.info("Fetching channels for organization: All Vtubers")
            offset = 0

            while api_call_count < max_api_calls:
                if api_call_count >= max_api_calls:
                    logger.warning(f"Reached maximum API call limit ({max_api_calls})")
                    break

                # Fetch channels with pagination
                params = {
                    "limit": str(limit),
                    "offset": str(offset),
                    "type": "vtuber",
                    "org": "All Vtubers",
                }

                # Add delay before request to avoid rate limiting
                await asyncio.sleep(request_delay)
                api_call_count += 1

                async with self.session.get(f"{self.BASE_URL}/channels", params=params) as response:
                    if response.status == 200:
                        channels = await response.json()

                        if not channels:
                            # No more channels to fetch
                            break

                        all_channels.extend(channels)

                        # Move to the next page
                        offset += len(channels)
                    elif response.status == 429:
                        logger.warning(
                            "Rate limited while fetching channels for All Vtubers, waiting longer"
                        )
                        # If rate limited, increase delay for future requests
                        request_delay = min(request_delay * 1.5, 5.0)
                        await asyncio.sleep(10)  # Wait 10 seconds before retrying
                        continue
                    else:
                        logger.error(f"Error fetching channels for All Vtubers: {response.status}")
                        break

            logger.info(
                f"Fetched a total of {len(all_channels)} channels in {api_call_count} API calls"
            )
            return all_channels
        except Exception:
            logger.exception("Exception fetching channels:")
            return []

    async def get_handle_info(self, handle: str) -> dict[str, Any] | None:
        await self.initialize()

        if self.session is None:
            logger.error("Session not initialized")
            return None

        url = f"{self.BASE_URL}/channels/{handle}"
        async with self.session.get(url) as response:
            if response.status == 200:
                return await response.json()
            elif response.status == 404:
                return None
            else:
                logger.error(f"Error fetching handle info for {handle}: {response.status}")
                return None


@dataclass
class StreamEvent:
    """Represents a streaming event from Holodex."""

    video_id: str
    channel_id: str
    title: str
    channel_name: str
    thumbnail: str
    status: str  # live, upcoming, ended
    start_time: str | None
    live_viewers: int | None
    members_only: bool

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "StreamEvent":
        """Create a StreamEvent from Holodex API response data.

        Args:
            data: Holodex API response data for a stream

        Returns:
            StreamEvent object
        """
        topic = data.get("topic_id", "").lower()
        return cls(
            video_id=data["id"],
            channel_id=data["channel"]["id"],
            title=data["title"],
            channel_name=data["channel"]["name"],
            thumbnail=f"https://i.ytimg.com/vi/{data['id']}/maxresdefault.jpg",
            status=data["status"],
            start_time=data.get("start_scheduled") or data.get("start_actual"),
            live_viewers=data.get("live_viewers"),
            members_only="membersonly" in topic,
        )


@dataclass
class ChatMessage:
    """Represents a chat message from Holodex."""

    video_id: str
    channel_id: str
    author: str
    timestamp: int
    video_offset: float
    message: str
    is_tl: bool
    is_moderator: bool
    is_vtuber: bool
    is_verified: bool
    source: str

    @classmethod
    def from_socket_message(
        cls, video_id: str, data: dict[str, Any], channel_id: str = ""
    ) -> "ChatMessage":
        """Create a ChatMessage from Holodex WebSocket message data.

        Args:
            video_id: The YouTube video ID this message belongs to
            data: Holodex WebSocket message data
            channel_id: The YouTube channel ID this message belongs to

        Returns:
            ChatMessage object
        """

        # Clean up the message - remove URLs
        return cls(
            video_id=video_id,
            channel_id=channel_id,
            author=data.get("name", "Unknown"),
            timestamp=data.get("timestamp", 0),
            video_offset=data.get("video_offset", 0.0),
            message=data.get("message", ""),
            is_tl=data.get("is_tl", False),
            is_moderator=data.get("is_moderator", False),
            is_vtuber=data.get("is_vtuber", False),
            is_verified=data.get("is_verified", False),
            source=data.get("source", ""),
        )


class HolodexManager:
    """Manager for handling Holodex API interactions and relay functionality."""

    def __init__(self, api_key: str, cache_dir: str = ""):
        """Initialize the Holodex Manager.

        Args:
            api_key: Holodex API key
            cache_dir: Directory to store the channel cache. If empty, uses the current directory.
        """
        self.api = HolodexAPI(api_key)
        self.current_streams: dict[str, StreamEvent] | None = None  # video_id -> StreamEvent
        self.active_subscriptions: set[str] = set()  # Set of video_ids currently subscribed to
        self.running = False
        self.update_interval = 60  # seconds
        self.sync_offset_seconds = 30  # seconds after interval boundary to sync
        self.api_key = api_key
        self.tracked_channels: set[str] = set()  # Set of YouTube channel IDs to track
        self.channel_handles: dict[str, Any] = {}  # Cache of channel info by handle

        # WebSocket connection
        self.ws = None
        self.ws_connected = False
        self.video_handlers: dict[str, asyncio.Task] = {}
        self.session_id: str | None = None
        self.ws_connecting_lock = asyncio.Lock()
        self.ws_task = None

        # Stream event skip tracking
        self.initialization_complete_time: float | None = None

        # Channel cache
        if not cache_dir:
            # Use the directory where the config file is located
            config_dir = os.environ.get("OTOMOPY_CONFIG_DIR", ".")
            self.channel_cache = ChannelCache(config_dir)
        else:
            self.channel_cache = ChannelCache(cache_dir)

    async def start(
        self,
        tracked_channels: set[str],
        stream_callback: Callable[[StreamEvent], Awaitable[None]],
        chat_callback: Callable[[ChatMessage], Awaitable[None]],
        vtuber_callback: Callable[[ChatMessage], Awaitable[None]],
    ):
        """Start the Holodex stream tracking.

        Args:
            tracked_channels: Set of YouTube channel IDs to track
            stream_callback: Function to call when stream events are detected
            chat_callback: Function to call when chat messages are detected
        """
        self.running = True
        self.stream_callback = stream_callback
        self.chat_callback = chat_callback
        self.vtuber_callback = vtuber_callback
        self.tracked_channels = tracked_channels

        # Load channel cache or fetch channels if cache is invalid
        await self._initialize_channel_cache()

        # Mark initialization as complete
        self.initialization_complete_time = time.time()
        logger.info(f"Channel cache initialization complete.")

        # Start WebSocket connection (only if not already connected)
        if not self.ws_task or self.ws_task.done():
            self.ws_task = asyncio.create_task(self._websocket_loop())

        # Wait a moment for WebSocket to connect before starting stream updates
        await asyncio.sleep(2)

        # Create task for stream updates
        stream_task = asyncio.create_task(self._stream_update_loop())

        # Wait for the tasks to complete (or be cancelled)
        await asyncio.gather(stream_task, self.ws_task, return_exceptions=True)

    async def _initialize_channel_cache(self):
        """Initialize the channel cache.

        This method loads the channel cache if it exists and is valid.
        Otherwise, it fetches channels from Holodex API and updates the cache.
        If the cache exists but is stale, it will fetch additional channels
        and merge them with the existing cache.
        """
        # Try to load the cache first
        cache_loaded = self.channel_cache.load_cache()

        if cache_loaded and self.channel_cache.is_cache_valid():
            logger.info(
                f"Using existing channel cache with {len(self.channel_cache.get_channels())} channels"
            )
            return

        existing_channels = []
        if cache_loaded:
            # If cache exists but is stale, we'll use it as a starting point
            existing_channels = self.channel_cache.get_channels()
            logger.info(f"Found stale cache with {len(existing_channels)} channels, updating...")

        # Fetch new channels from API
        logger.info("Fetching channels from Holodex API...")
        new_channels = await self.api.get_all_channels()

        if new_channels:
            # Filter new channels to only include useful ones
            filtered_channels = []
            channel_keys = [
                "id",
                "name",
                "yt_handle",
                "english_name",
                "org",
                "photo",
                "type",
                "suborg",
            ]
            for channel in new_channels:
                # Only include active channels with both name and ID
                if channel.get("id") and channel.get("name") and not channel.get("inactive", False):
                    # Create simplified channel object with additional info
                    filtered_channels.append({key: channel.get(key, "") for key in channel_keys})

            # Update the cache with filtered channels
            if filtered_channels:
                self.channel_cache.update_cache(filtered_channels)
                logger.info(f"Cached {len(filtered_channels)} channels from Holodex API")
            else:
                logger.warning("No valid channels found from Holodex API")
        elif existing_channels:
            # If we couldn't fetch new channels but have existing ones, refresh the cache timestamp
            logger.warning("Failed to fetch new channels, using existing cache")
            self.channel_cache.update_cache(existing_channels)
        else:
            logger.error("Failed to fetch channels from Holodex API and no cache exists")

    async def stop(self):
        """Stop the Holodex stream tracking."""
        self.running = False

        # Cancel the WebSocket task
        if self.ws_task and not self.ws_task.done():
            self.ws_task.cancel()
            try:
                await self.ws_task
            except asyncio.CancelledError:
                pass

        # Cancel all video handler tasks
        for video_id, task in self.video_handlers.items():
            if not task.done():
                task.cancel()

        # Close WebSocket connection
        if hasattr(self, "ws") and self.ws and not self.ws.closed:
            await self.ws.close()

        # Close WebSocket session
        if hasattr(self, "ws_session") and self.ws_session and not self.ws_session.closed:
            await self.ws_session.close()
            self.ws_session = None

        # Close the API HTTP client
        await self.api.close()

    async def update_channels(self, new_channels: set[str]):
        """Update the set of YouTube channels being tracked.

        Args:
            new_channels: New set of YouTube channel IDs to track
        """
        old_channels = self.tracked_channels.copy()
        self.tracked_channels = new_channels

        # Log the change
        added_channels = new_channels - old_channels
        removed_channels = old_channels - new_channels

        if added_channels:
            logger.info(f"Added {len(added_channels)} new channels to track")
            # Immediately update streams to pick up content from new channels
            if self.running:
                logger.info("Triggering immediate stream update for new channels")
                try:
                    await self._update_streams(self.tracked_channels)
                except Exception:
                    logger.exception("Error during immediate stream update")

        if removed_channels:
            logger.info(f"Removed {len(removed_channels)} channels from tracking")
            # Immediately clean up streams from removed channels
            self._cleanup_removed_channels(removed_channels)

        logger.info(f"Now tracking {len(self.tracked_channels)} total channels")

    async def get_channel(self, name: str) -> dict[str, Any] | None:
        if name.startswith("@"):
            name = name.lower()
            # This is a handle
            logger.info(f"Fetching channel info for handle {name}")
            channel = self.channel_cache.get_channel_by_handle(name)
            if channel is None:
                logger.info(f"Handle {name} not found in cache, fetching from API")
                channel = await self.api.get_handle_info(name)
                if channel is None:
                    logger.info(f"API did not return a channel for handle {name}")
                    return None
                self.channel_cache._channel_by_handle[name] = channel

            name = channel["name"]

        return self.channel_cache.get_channel_by_name(name)

    def _cleanup_removed_channels(self, removed_channels: set[str]):
        """Clean up streams from channels that are no longer being tracked.

        Args:
            removed_channels: Set of channel IDs that were removed from tracking
        """
        if self.current_streams is None:
            return

        # Find streams that belong to removed channels
        streams_to_remove = []
        for video_id, stream in self.current_streams.items():
            if stream.channel_id in removed_channels:
                streams_to_remove.append(video_id)
                logger.info(
                    f"Cleaning up stream from removed channel: {stream.channel_name} - {stream.title}"
                )

        # Remove streams from current_streams and schedule unsubscription
        for video_id in streams_to_remove:
            if video_id in self.current_streams:
                del self.current_streams[video_id]

            # Schedule unsubscription from chat if we're subscribed
            if video_id in self.active_subscriptions and self.running:
                # Create a task to unsubscribe from chat
                asyncio.create_task(self._unsubscribe_from_chat(video_id))

    def _calculate_sleep_until_next_sync(self) -> float:
        """Calculate sleep time until next synchronized interval.

        This synchronizes the update loop to occur at predictable times based on
        system clock. For example, with a 300-second (5-minute) interval and
        sync_offset_seconds=5, updates will occur at:
        - 00:05:05, 00:10:05, 00:15:05, etc.

        Returns:
            Sleep duration in seconds until the next sync point
        """
        now = datetime.now(timezone.utc)

        # Calculate seconds since midnight
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        seconds_since_midnight = (now - midnight).total_seconds()

        # Find the next sync point: n * update_interval + sync_offset_seconds
        # where n is the smallest integer such that the result > seconds_since_midnight
        current_cycle = int(
            (seconds_since_midnight - self.sync_offset_seconds) // self.update_interval
        )
        next_sync_seconds = (current_cycle + 1) * self.update_interval + self.sync_offset_seconds

        # Handle case where we've passed midnight (next sync is tomorrow)
        if next_sync_seconds >= 86400:  # seconds in a day
            next_sync_seconds -= 86400
            next_sync_time = midnight + timedelta(days=1, seconds=next_sync_seconds)
        else:
            next_sync_time = midnight + timedelta(seconds=next_sync_seconds)

        # Calculate sleep duration
        sleep_seconds = (next_sync_time - now).total_seconds()

        # Ensure we don't sleep for negative time or too long
        return max(1.0, min(sleep_seconds, self.update_interval))

    async def _stream_update_loop(self):
        """Run the stream update loop synchronized with system time."""
        while self.running:
            try:
                await self._update_streams(self.tracked_channels)
                sleep_duration = self._calculate_sleep_until_next_sync()

                # Calculate next sync time for logging
                next_sync_time = datetime.now(timezone.utc) + timedelta(seconds=sleep_duration)
                logger.info(
                    f"Stream update complete. Next update at {next_sync_time.strftime('%H:%M:%S')} UTC "
                    f"(sleeping {sleep_duration:.1f}s)"
                )

                await asyncio.sleep(sleep_duration)
            except Exception:
                logger.exception("Error in stream update loop")
                await asyncio.sleep(5)  # Short delay before retry on error

    async def _establish_websocket_session(self):
        """Create or refresh the aiohttp ClientSession for WebSocket connections."""
        if not self.ws_session or self.ws_session.closed:
            if self.ws_session:
                await self.ws_session.close()
            self.ws_session = aiohttp.ClientSession()

    async def _connect_to_websocket(self):
        """Establish WebSocket connection to Socket.IO endpoint."""
        url = "wss://holodex.net/api/socket.io/?EIO=4&transport=websocket"
        logger.debug(f"Connecting to Socket.IO WebSocket: {url}")
        if not self.ws_session:
            raise RuntimeError("WebSocket session not initialized")

        return await self.ws_session.ws_connect(
            url,
            timeout=aiohttp.ClientWSTimeout(ws_close=30),  # pyright: ignore
            receive_timeout=None,  # Disable receive timeout for persistent connection
            heartbeat=30,
        )

    async def _handle_socketio_handshake(self, ws):
        """Handle Socket.IO handshake protocol."""
        msg = await ws.receive(timeout=10)
        if not (msg.type == aiohttp.WSMsgType.TEXT and msg.data.startswith("0")):
            logger.error(
                f"Invalid Socket.IO handshake: {msg.data if msg.type == aiohttp.WSMsgType.TEXT else msg.type}"
            )
            return False

        # Parse Socket.IO handshake
        handshake_data = json.loads(msg.data[1:])
        self.session_id = handshake_data.get("sid")
        logger.info(f"Socket.IO handshake successful. Session ID: {self.session_id}")

        # Send Socket.IO connect message
        await ws.send_str("40")
        logger.debug("Sent Socket.IO connect message")
        return True

    async def _resubscribe_to_streams(self):
        """Re-subscribe to all active streams after reconnection."""
        # Wait a bit for connection to stabilize before subscribing
        await asyncio.sleep(1)

        # Re-subscribe to all active streams
        for video_id in list(self.active_subscriptions):
            await self._subscribe_to_chat(video_id)
            await asyncio.sleep(0.1)  # Small delay between subscriptions

        # Also check for any streams we might have missed while disconnected
        if hasattr(self, "stream_callback") and self.current_streams is not None:
            for video_id, event in self.current_streams.items():
                if (
                    event.status in ["live", "upcoming"]
                    and not event.members_only
                    and video_id not in self.active_subscriptions
                ):
                    logger.info(f"Re-subscribing to missed stream: {video_id}")
                    await self._subscribe_to_chat(video_id)
                    await asyncio.sleep(0.1)  # Small delay between subscriptions

    async def _process_messages_loop(self, ws):
        """Main message processing loop for WebSocket messages."""
        while self.running and not ws.closed:
            try:
                # Receive message with timeout
                msg = await ws.receive(timeout=10)

                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._process_websocket_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    close_code = ws.close_code
                    close_reason = getattr(ws, "close_reason", "Unknown")
                    logger.warning(
                        f"WebSocket connection closed by server - Code: {close_code}, Reason: {close_reason}"
                    )
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")
                    break

            except asyncio.TimeoutError:
                # This is expected for the receive timeout
                continue
            except Exception:
                logger.exception("Error processing WebSocket message")
                break

    async def _websocket_loop(self):
        """Main WebSocket connection loop with proper Socket.IO protocol handling."""
        retry_delay = 1
        max_retry_delay = 60
        self.ws_session = None

        try:
            while self.running:
                # Use a lock to prevent multiple concurrent connections
                async with self.ws_connecting_lock:
                    if self.ws_connected and self.ws and not self.ws.closed:
                        # Already connected, just wait a bit and check again
                        await asyncio.sleep(1)
                        continue

                    try:
                        # Create a ClientSession if it doesn't exist
                        await self._establish_websocket_session()

                        # Connect to Socket.IO endpoint
                        async with await self._connect_to_websocket() as ws:
                            self.ws = ws
                            logger.info("WebSocket connection established")

                            # Handle Socket.IO handshake
                            if not await self._handle_socketio_handshake(ws):
                                break

                            self.ws_connected = True
                            retry_delay = 1  # Reset retry delay on successful connection

                            # Re-subscribe to all active streams
                            await self._resubscribe_to_streams()

                            # Main message processing loop
                            await self._process_messages_loop(ws)

                        # If we get here, the connection was closed
                        if self.ws and hasattr(self.ws, "close_code"):
                            logger.info(
                                f"WebSocket connection closed (Code: {self.ws.close_code}), will reconnect"
                            )
                        else:
                            logger.info("WebSocket connection closed, will reconnect")
                        self.ws_connected = False
                        self.ws = None

                    except asyncio.TimeoutError:
                        logger.error("WebSocket connection timeout")
                        self.ws_connected = False
                        self.ws = None
                        await asyncio.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, max_retry_delay)

                    except (aiohttp.ClientError, ConnectionRefusedError):
                        logger.exception("WebSocket connection error")
                        self.ws_connected = False
                        self.ws = None
                        await asyncio.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, max_retry_delay)

                    except Exception:
                        logger.exception("Unexpected WebSocket error:")
                        self.ws_connected = False
                        self.ws = None
                        await asyncio.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, max_retry_delay)

                # Wait before trying again
                if self.running:
                    await asyncio.sleep(min(retry_delay, 5))

                if not self.running:
                    break
        finally:
            # Clean up session
            self.ws_connected = False
            if self.ws_session and not self.ws_session.closed:
                await self.ws_session.close()  # pyright: ignore
                self.ws_session = None

    async def _handle_socketio_protocol_message(self, message: str) -> bool:
        """Handle Socket.IO protocol messages (ping/pong, connect/disconnect).

        Returns True if the message was handled, False otherwise.
        """
        if message == "3":  # pong
            logger.debug("Received Socket.IO pong")
            return True
        elif message == "2":  # ping from server
            logger.debug("Received Socket.IO ping, sending pong")
            if self.ws and not self.ws.closed:
                try:
                    await self.ws.send_str("3")  # Send pong response
                    logger.debug("Sent Socket.IO pong response")
                except Exception:
                    logger.exception("Failed to send pong response")
            return True
        elif message.startswith("40"):  # Socket.IO connect
            logger.debug("Socket.IO connection established")
            return True
        elif message.startswith("41"):  # Socket.IO disconnect
            logger.warning("Socket.IO disconnection received")
            return True

        return False

    async def _handle_subscribe_success(self, event_data: dict):
        """Handle successful chat subscription events."""
        video_id = event_data.get("id")
        logger.info(f"Successfully subscribed to chat for video {video_id}")

    async def _handle_subscribe_error(self, event_data: dict):
        """Handle chat subscription error events."""
        video_id = event_data.get("id")
        error_msg = event_data.get("message", "Unknown error")
        logger.error(f"Error subscribing to chat for video {video_id}: {error_msg}")
        if video_id in self.active_subscriptions:
            self.active_subscriptions.remove(video_id)

    async def _handle_chat_event(self, event_name: str, event_data: dict):
        """Handle chat message events for a specific video."""
        if self.current_streams is None:
            return
        video_id = event_name.split("/")[0]
        logger.debug(f"Processing chat event for video {video_id}: {event_name}")

        # Process the chat message if it has a name (indicates it's a chat, not a status update)
        if event_data.get("name"):
            logger.info(
                f"Received chat message from video {video_id}: {event_data.get('name')} - {event_data.get('message')}"
            )
            logger.debug(f"Full message data: {event_data}")

            # Look up the YouTube channel ID from the current streams
            channel_id = ""
            if video_id in self.current_streams:
                channel_id = self.current_streams[video_id].channel_id

            chat_message = ChatMessage.from_socket_message(video_id, event_data, channel_id)

            if not chat_message.message.strip():
                # Received an empty message, don't process it
                return

            if chat_message.is_vtuber:
                await self.vtuber_callback(chat_message)
            else:
                await self.chat_callback(chat_message)
        elif event_data.get("type") == "end":
            # Chat ended for this video
            logger.info(f"Chat ended for video {video_id}")
            if video_id in self.active_subscriptions:
                self.active_subscriptions.remove(video_id)
        else:
            logger.debug(f"Received non-chat message for video {video_id}: {event_data}")

    async def _parse_and_handle_socketio_event(self, message: str):
        """Parse and handle Socket.IO event messages (those starting with '42')."""
        json_str = ""  # Initialize to avoid unbound variable error
        try:
            # Extract the JSON part of the message
            json_str = message[2:]  # Remove "42" prefix
            if not json_str:
                return

            data = json.loads(json_str)

            # Handle different event types
            if isinstance(data, list) and len(data) >= 2:
                event_name = data[0]
                event_data = data[1]

                if event_name == "subscribeSuccess":
                    await self._handle_subscribe_success(event_data)
                elif event_name == "subscribeError":
                    await self._handle_subscribe_error(event_data)
                elif "/" in event_name and event_name.endswith("/en"):
                    await self._handle_chat_event(event_name, event_data)
                else:
                    logger.debug(f"Received unknown event: {event_name} with data: {event_data}")

        except json.JSONDecodeError:
            logger.exception(f"Failed to parse Socket.IO event JSON: {json_str}, error:")
        except Exception:
            logger.exception("Error handling Socket.IO event:")

    async def _process_websocket_message(self, message: str):
        """Process incoming Socket.IO WebSocket messages."""
        if not message:
            return

        logger.debug(f"Received WebSocket message: {message}")

        try:
            # Handle Socket.IO protocol messages first
            if await self._handle_socketio_protocol_message(message):
                return

            # Handle Socket.IO events (start with "42")
            if message.startswith("42"):
                await self._parse_and_handle_socketio_event(message)
            else:
                logger.debug(f"Received unhandled Socket.IO message: {message}")

        except Exception:
            logger.exception("Error processing WebSocket message:")

    def _is_stream_more_than_24h_away(self, event: StreamEvent) -> bool:
        """Check if a stream is more than 24 hours in the future.

        Args:
            event: StreamEvent to check

        Returns:
            True if stream starts more than 24 hours from now
        """
        if not event.start_time:
            return False

        try:
            # Parse the ISO format datetime string
            start_time = datetime.fromisoformat(event.start_time.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)

            # Check if more than 24 hours away
            return start_time > now + timedelta(hours=24)
        except (ValueError, AttributeError):
            logger.exception(
                f"Could not parse start_time '{event.start_time}' for stream {event.video_id}:"
            )
            return False

    async def _update_streams(self, tracked_channels: set[str]):
        """Update the current streams and detect changes.

        Args:
            tracked_channels: Set of YouTube channel IDs to track
        """
        if not tracked_channels:
            logger.debug("No tracked channels, skipping stream update")
            return

        logger.debug(f"Updating streams for {len(tracked_channels)} tracked channels")

        # Fetch current live/upcoming streams from Holodex
        live_data = await self.api.get_live_streams(tracked_channels)
        if live_data is None:
            logger.error("Failed to fetch live streams from Holodex API")
            return

        logger.debug(f"Fetched {len(live_data)} live/upcoming streams from Holodex API")

        # Convert to StreamEvent objects
        current_streams = {}
        for item in live_data:
            event = StreamEvent.from_api_response(item)

            current_streams[event.video_id] = event
            logger.debug(
                f"Found stream: {event.channel_name} - {event.title} - {event.status} - {event.video_id}"
            )

        # Detect new streams or status changes
        for video_id, event in current_streams.items():
            # If this is a new stream or the status has changed
            if (
                self.current_streams is None
                or video_id not in self.current_streams
                or self.current_streams[video_id].status != event.status
            ):
                logger.info(
                    f"Stream change detected: {event.channel_name} - {event.title} - {event.status}"
                )
                # Don't process streams that are upcoming and more than 24 hours away
                if self.current_streams is not None and (
                    event.status != "upcoming" or not self._is_stream_more_than_24h_away(event)
                ):
                    # Call the callback with the event
                    try:
                        await self.stream_callback(event)
                    except Exception as e:
                        logger.error(f"Error calling stream callback: {e}")

                # If the stream is live or upcoming and NOT members-only, subscribe to its chat
                if (
                    event.status in ["live", "upcoming"]
                    and not event.members_only
                    and video_id not in self.active_subscriptions
                ):
                    logger.info(f"Subscribing to chat for {event.status} stream: {event.video_id}")
                    # Wait for WebSocket to be connected before subscribing
                    if self.ws_connected:
                        await self._subscribe_to_chat(video_id)
                    else:
                        logger.warning(
                            f"WebSocket not connected, will retry subscription for {video_id} later"
                        )

                # If a previously subscribed stream is now members-only, unsubscribe from it
                if event.members_only and video_id in self.active_subscriptions:
                    logger.info(
                        f"Stream {event.video_id} is now members-only, unsubscribing from chat"
                    )
                    await self._unsubscribe_from_chat(video_id)

        # Check for ended streams and unsubscribe from their chats
        if self.current_streams is not None:
            for video_id in list(self.current_streams.keys()):
                if video_id not in current_streams:
                    # Stream has ended or is no longer tracked
                    logger.info(f"Stream ended or no longer tracked: {video_id}")
                    if video_id in self.active_subscriptions:
                        await self._unsubscribe_from_chat(video_id)

        # Update our stored state
        self.current_streams = current_streams
        logger.debug(
            f"Updated stream state: {len(current_streams)} current streams, {len(self.active_subscriptions)} active subscriptions"
        )

    async def _subscribe_to_chat(self, video_id: str):
        """Subscribe to chat messages for a specific video.

        Args:
            video_id: YouTube video ID
        """
        if not self.ws_connected or not self.ws:
            logger.error(f"Cannot subscribe to chat for video {video_id}: WebSocket not connected")
            return

        logger.info(f"Subscribing to chat for video {video_id}")

        # Add to active subscriptions
        self.active_subscriptions.add(video_id)

        # Send subscription message to WebSocket
        try:
            # Format as Socket.IO event message: "42" + JSON array with event name and data
            message = f'42["subscribe",{{"video_id":"{video_id}","lang":"en"}}]'
            logger.debug(f"Sending subscription message: {message}")
            await self.ws.send_str(message)
            logger.info(f"Subscription message sent for video {video_id}")
        except Exception:
            logger.exception(f"Error subscribing to chat for video {video_id}:")
            if video_id in self.active_subscriptions:
                self.active_subscriptions.remove(video_id)

    async def _unsubscribe_from_chat(self, video_id: str):
        """Unsubscribe from chat messages for a specific video.

        Args:
            video_id: YouTube video ID
        """
        if not self.ws_connected or not self.ws:
            logger.debug("Cannot unsubscribe from chat: WebSocket not connected")
            return

        logger.info(f"Unsubscribing from chat for video {video_id}")

        # Send unsubscription message to WebSocket
        try:
            # Format as Socket.IO event message: "42" + JSON array with event name and data
            message = f'42["unsubscribe",{{"video_id":"{video_id}","lang":"en"}}]'
            await self.ws.send_str(message)
        except Exception:
            logger.exception(f"Error unsubscribing from chat for video {video_id}:")

        # Remove from active subscriptions
        if video_id in self.active_subscriptions:
            self.active_subscriptions.remove(video_id)
