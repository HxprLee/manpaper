
import requests
from .data_models import OnlineWallpaperItem

def search_wallhaven(query: str, api_key: str, sfw: bool, sketchy: bool, nsfw: bool, general: bool, anime: bool, people: bool, resolution: str, atleast: str, ratios: str, page: int = 1):
    """
    Searches Wallhaven for wallpapers.
    """
    if not api_key:
        return {"error": "API key is not set."}

    purity = f"{'1' if sfw else '0'}{'1' if sketchy else '0'}{'1' if nsfw else '0'}"
    categories = f"{'1' if general else '0'}{'1' if anime else '0'}{'1' if people else '0'}"

    params = {
        "apikey": api_key,
        "purity": purity,
        "categories": categories,
        "page": page
    }
    if query:
        params['q'] = query
    if resolution:
        params['resolutions'] = resolution
    if atleast:
        params['atleast'] = atleast
    if ratios:
        params['ratios'] = ratios
    
    print(f"Triggering search with purity: SFW={sfw}, Sketchy={sketchy}, NSFW={nsfw}")
    print(f"Triggering search with categories: General={general}, Anime={anime}, People={people}")
    print(f"Wallhaven API params: {params}")
    try:
        response = requests.get("https://wallhaven.cc/api/v1/search", params=params)
        response.raise_for_status()  # Raise an exception for bad status codes
        data = response.json()
        
        results = []
        for wall in data.get("data", []):
            item = OnlineWallpaperItem(
                wall_id=wall.get("id"),
                thumbnail_url=wall.get("thumbs", {}).get("small"),
                full_url=wall.get("path"),
                purity=wall.get("purity"),
                resolution=wall.get("resolution")
            )
            results.append(item)
        return results

    except requests.exceptions.RequestException as e:
        return {"error": str(e)}

