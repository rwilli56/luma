"""Seren-style navigation, implemented using Luma's own service adapters."""

ROOT = [
 ('Discover Movies', 'discover_movies'), ('Discover TV Shows', 'discover_shows'),
 ('My Movies', 'my_movies'), ('My Shows', 'my_shows'), ('My Files', 'files'),
 ('Search', 'search'), ('Tools', 'tools'), ('Home Dashboard', 'dashboard'),
]
DISCOVERY = [
 ('Most Popular', 'popular'), ('Popular Recent {noun}', 'popular_recent'),
 ('Recommended For You', 'recommended'), ('Trending', 'trending'),
 ('Trending Recent {noun}', 'trending_recent'), ('Most Played', 'played'),
 ('Most Watched', 'watched'), ('Most Collected', 'collected'),
 ('Trending {singular} Lists', 'lists_trending'), ('Popular {singular} Lists', 'lists_popular'),
 ('Most Anticipated', 'anticipated'), ('Recently Updated', 'updated'),
 ('Genres', 'genres'), ('Years', 'years'), ('By Actor', 'actor'), ('Search', 'query'),
]
MY_MOVIES = [
 ('Finish Watching', 'continue'), ('Collection', 'collection'), ('Watchlist', 'watchlist'),
 ('My Movie Lists', 'own_lists'), ('My Liked Movie Lists', 'liked_lists'), ('My Watched Movies', 'history'),
]
MY_SHOWS = [
 ('Finish Watching', 'continue'), ('Collection', 'collection'), ('Watchlist', 'watchlist'),
 ('Recently Watched', 'recent'), ('Next Up', 'next'), ('Upcoming Episodes', 'upcoming'),
 ('Unfinished Shows in Collection', 'unfinished'), ('Recent Episodes', 'recent_episodes'),
 ('My Show Lists', 'own_lists'), ('My Liked Show Lists', 'liked_lists'), ('My Watched Episodes', 'history'),
]
TOOLS = [
 ('Provider Tools', 'providers'), ('Premium Services', 'services'), ('Clear Cache', 'clear_cache'),
 ('Clear Local Torrent Cache', 'clear_sources'), ('Clear Search History', 'clear_searches'),
 ('Open Settings Menu', 'settings'), ('Wipe Addon Data', 'wipe'), ('Trakt Sync Tools', 'trakt_tools'),
 ('Download Manager', 'downloads'),
]
PROVIDERS = [('Check For Updates', 'provider_updates'), ('Manage Provider Packages', 'provider_settings')]
TRAKT_TOOLS = [('Flush Activities', 'flush_activities'), ('Force Sync', 'sync'), ('Rebuild Trakt Database', 'rebuild_trakt')]


def discovery(kind):
    noun, singular = ('Movies', 'Movie') if kind == 'movie' else ('Shows', 'Show')
    rows = [(text.format(noun=noun, singular=singular), key) for text, key in DISCOVERY]
    rows.insert(11, ('Box Office Top 10', 'boxoffice')) if kind == 'movie' else rows.insert(5, ('New TV Shows', 'new'))
    if kind == 'show':
        rows.insert(-4, ('Networks', 'networks'))
    return rows
