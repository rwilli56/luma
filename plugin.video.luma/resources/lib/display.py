"""Configure Kodi's native refresh switching; never synthesize stream frame rates."""
import json

REFRESH = 'videoplayer.adjustrefreshrate'
SYNC_CLOCK = 'videoplayer.usedisplayasclock'
NAMES = {0: 'Off', 1: 'Always', 2: 'On start/stop', 3: 'On start'}


def exchange(requests, rpc=None):
    if rpc is None:
        import xbmc
        rpc = xbmc.executeJSONRPC
    result = json.loads(rpc(json.dumps(requests)))
    if not isinstance(result, list):
        raise ValueError('Invalid Kodi settings response')
    return {item['id']: item for item in result}


def read(rpc=None):
    result = exchange([{'jsonrpc': '2.0', 'id': i, 'method': 'Settings.GetSettingValue',
                        'params': {'setting': key}} for i, key in enumerate((REFRESH, SYNC_CLOCK))], rpc)
    return {key: result[i]['result']['value'] for i, key in enumerate((REFRESH, SYNC_CLOCK))}


def configure(enabled=True, rpc=None):
    try:
        values = read(rpc)
        if enabled:
            desired = {REFRESH: 2, SYNC_CLOCK: False}
            changed = [(key, value) for key, value in desired.items() if values[key] != value]
            if changed:
                results = exchange([{'jsonrpc': '2.0', 'id': i, 'method': 'Settings.SetSettingValue',
                                     'params': {'setting': key, 'value': value}}
                                    for i, (key, value) in enumerate(changed)], rpc)
                if any(results[i].get('result') is not True for i in range(len(changed))):
                    return False, 'Frame-rate setup incomplete. Check Kodi Player > Videos settings.'
                values.update(desired)
        ready = values[REFRESH] in (1, 2, 3) and values[SYNC_CLOCK] is False
        text = 'Adjust display refresh rate: {}\nSync playback to display: {}'.format(
            NAMES.get(values[REFRESH], 'Unknown'), 'On' if values[SYNC_CLOCK] else 'Off')
        return ready, text
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError):
        return False, 'Unable to read display settings. Set Kodi Player > Videos > Adjust display refresh rate to On start/stop.'
