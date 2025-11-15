from __future__ import annotations

import httpx
from typing import Any, Dict, Optional
from urllib.parse import quote_plus

from .config import AppConfig


class JellyseerrClient:
    def __init__(self, config: AppConfig):
        self._base_url = f"{config.jellyseerr_url}/api/v1"
        self._timeout = config.timeout
        self._headers = {
            "X-Api-Key": config.jellyseerr_api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        # Lazy-created async client
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(headers=self._headers, timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Any:
        client = await self._get_client()
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        try:
            resp = await client.request(method.upper(), url, params=params or None, json=json or None)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            detail = e.response.text
            status_code = e.response.status_code
            error_msg = f"Jellyseerr API error for '{e.request.method} {e.request.url}': HTTP {status_code}"
            if detail:
                error_msg += f" - {detail}"
            else:
                error_msg += f" - {e.response.reason_phrase or 'Unknown error'}"
            raise RuntimeError(error_msg) from e
        except httpx.RequestError as e:
            error_msg = f"Jellyseerr connection error for '{method.upper()} {url}': {type(e).__name__}"
            if str(e):
                error_msg += f" - {e}"
            raise RuntimeError(error_msg) from e
        except Exception as e:
            raise RuntimeError(f"Unexpected error calling Jellyseerr API '{method.upper()} {url}': {type(e).__name__}: {e}") from e


    # Convenience methods for common operations
    async def search_media(self, query: str, limit: int = 20) -> Any:
        # URL encode the query to handle spaces and special characters
        encoded_query = quote_plus(query)
        return await self.request("GET", "search", params={"query": encoded_query})

    async def request_media(
        self,
        media_id: int,
        media_type: str,
        is_4k: bool = False,
        seasons: Optional[list[int]] = None,
        server_id: Optional[int] = None,
        service_slug: Optional[str] = None,
    ) -> Any:
        """
        Create a media request in Jellyseerr.
        
        Args:
            media_id: The media ID from search results
            media_type: "movie" or "tv"
            is_4k: Whether to request 4K quality (default: False)
            seasons: For TV shows, list of season numbers to request (None = all seasons)
            server_id: Specific server/service ID to use (overrides service_slug)
            service_slug: Specific service slug to use (e.g., "radarr", "sonarr", "radarr_4k")
        
        Returns:
            The created request data from Jellyseerr API
        """
        # Validate media_type
        if media_type not in ("movie", "tv"):
            raise ValueError(f"Invalid media_type '{media_type}'. Must be 'movie' or 'tv'")
        
        # Discover media details to find the correct media ID and available services
        media_details = await self.request("GET", f"{media_type}/{media_id}")
        
        # Get available services
        services = media_details.get("services", [])
        if not services:
            raise ValueError(f"No services available for media_id {media_id} (media_type: {media_type})")
        
        # Select service
        service = None
        if server_id:
            # Use explicitly provided server_id
            service = next((s for s in services if s.get("id") == server_id), None)
            if not service:
                available_ids = [s.get("id") for s in services if s.get("id") is not None]
                raise ValueError(
                    f"Server ID {server_id} not found for media_id {media_id}. "
                    f"Available server IDs: {available_ids}"
                )
        elif service_slug:
            # Use explicitly provided service_slug
            service = next((s for s in services if s.get("slug") == service_slug), None)
            if not service:
                valid_slugs = [s.get("slug") for s in services if s.get("slug")]
                valid_slugs_str = ", ".join(f"'{slug}'" for slug in valid_slugs) if valid_slugs else "none"
                raise ValueError(
                    f"Service slug '{service_slug}' not found for media_id {media_id}. "
                    f"Available services: {valid_slugs_str}"
                )
        else:
            # Auto-select service based on media_type and is_4k preference
            preferred_slug = "radarr" if media_type == "movie" else "sonarr"
            if is_4k:
                preferred_slug += "_4k"
            
            # Try preferred service first
            service = next((s for s in services if s.get("slug") == preferred_slug), None)
            
            # If preferred not found, try non-4K version
            if not service and is_4k:
                fallback_slug = "radarr" if media_type == "movie" else "sonarr"
                service = next((s for s in services if s.get("slug") == fallback_slug), None)
            
            # If still not found, use first available service
            if not service:
                service = services[0]
        
        # Build request payload
        payload: Dict[str, Any] = {
            "mediaId": media_details["id"],
            "mediaType": media_type,
            "is4k": is_4k,
            "serverId": service["id"],
        }
        
        # For TV shows, add seasons if specified
        if media_type == "tv":
            if seasons is not None:
                # Validate seasons exist in the media
                available_seasons = media_details.get("seasons", [])
                available_season_numbers = [s.get("seasonNumber") for s in available_seasons if s.get("seasonNumber") is not None]
                
                # Check if all requested seasons are available
                invalid_seasons = [s for s in seasons if s not in available_season_numbers]
                if invalid_seasons:
                    raise ValueError(
                        f"Invalid season numbers {invalid_seasons} for media_id {media_id}. "
                        f"Available seasons: {available_season_numbers}"
                    )
                
                # Build seasons array with full season objects
                payload["seasons"] = [
                    s for s in available_seasons
                    if s.get("seasonNumber") in seasons
                ]
            # If seasons is None, Jellyseerr will request all seasons by default
        
        return await self.request("POST", "request", json=payload)

    async def get_request(self, request_id: int) -> Any:
        return await self.request("GET", f"request/{request_id}")
