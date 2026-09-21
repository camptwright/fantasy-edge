"""Point-in-time weather features for research only, never serving multipliers.

Open-Meteo hourly contract: explicit UTC, Celsius, km/h and mm. Selection is
bounded to the kickoff hour through three following hours, not quarter timings.
"""
from datetime import datetime, timedelta, timezone
import math
import httpx

FIELDS = {'temperature_2m':'°C', 'relative_humidity_2m':'%', 'precipitation_probability':'%',
          'precipitation':'mm', 'wind_speed_10m':'km/h', 'wind_gusts_10m':'km/h', 'wind_direction_10m':'°'}


def features(payload, *, captured_at, kickoff, as_of, roof):
    if any(t.tzinfo is None for t in (captured_at,kickoff,as_of)):
        raise ValueError('Aware UTC-compatible timestamps required')
    base={'serving_enabled':False,'scope':'hourly_forecast_not_observed_weather','roof':roof}
    if not captured_at <= as_of < kickoff or as_of-captured_at > timedelta(hours=6):
        return {**base,'status':'unavailable_or_stale_at_prediction','hours':[]}
    if roof not in ('outdoor','closed','retractable_unknown'):
        return {**base,'status':'unverified_roof','hours':[]}
    if roof=='closed':
        return {**base,'status':'indoor_weather_not_applied','hours':[]}
    if not isinstance(payload,dict) or not isinstance(payload.get('hourly_units'),dict):
        return {**base,'status':'malformed_forecast','hours':[]}
    if payload.get('utc_offset_seconds') != 0 or any(payload.get('hourly_units',{}).get(k)!=v for k,v in FIELDS.items()):
        return {**base,'status':'unsupported_units_or_timezone','hours':[]}
    hourly=payload.get('hourly',{})
    if not isinstance(hourly,dict):return {**base,'status':'malformed_hourly_series','hours':[]}
    times=hourly.get('time',[])
    if not isinstance(times,list) or not all(isinstance(t,str) for t in times):
        return {**base,'status':'malformed_hourly_series','hours':[]}
    if len(set(times))!=len(times) or any(not isinstance(hourly.get(k),list) or len(hourly[k])!=len(times) for k in FIELDS):
        return {**base,'status':'malformed_hourly_series','hours':[]}
    start=kickoff.astimezone(timezone.utc).replace(minute=0,second=0,microsecond=0)
    wanted={(start+timedelta(hours=i)).isoformat() for i in range(4)}
    rows=[]
    for index,value in enumerate(times):
        try:
            at=datetime.fromisoformat(value.replace('Z','+00:00'))
            if at.tzinfo is None:
                at=at.replace(tzinfo=timezone.utc)  # provider explicitly requested UTC
        except (ValueError,TypeError,AttributeError):
            continue
        if at.isoformat() not in wanted:
            continue
        row={'at':at.isoformat()}
        for key in FIELDS:
            n=hourly[key][index]
            valid=isinstance(n,(int,float)) and not isinstance(n,bool) and math.isfinite(n)
            if key in ('relative_humidity_2m','precipitation_probability'): valid=valid and 0<=n<=100
            elif key=='wind_direction_10m': valid=valid and 0<=n<=360
            elif key!='temperature_2m': valid=valid and n>=0
            row[key]=n if valid else None
        rows.append(row)
    complete=len(rows)==4 and all(r[k] is not None for r in rows for k in FIELDS)
    return {**base,'status':'forecast_context' if complete else 'incomplete_forecast',
            'captured_at':captured_at.isoformat(),'hours':sorted(rows,key=lambda r:r['at']),
            'units':FIELDS,'exposure_confirmed':roof=='outdoor',
            'limitations':['Forecast capture time is not provider model issuance time.',
                'Hourly windows do not identify actual quarter start times.',
                'Retractable roof exposure needs event-specific confirmation.']}


async def fetch_forecast(latitude, longitude):
    """Caller must bind coordinates to the actual event venue, not home team."""
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (latitude,longitude)) or not (-90<=latitude<=90 and -180<=longitude<=180):
        raise ValueError('Valid event venue coordinates required')
    async with httpx.AsyncClient(timeout=15) as client:
        response=await client.get('https://api.open-meteo.com/v1/forecast',params={
            'latitude':latitude,'longitude':longitude,'hourly':','.join(FIELDS),'timezone':'UTC',
            'temperature_unit':'celsius','wind_speed_unit':'kmh','precipitation_unit':'mm','forecast_days':7})
        response.raise_for_status()
        return {'captured_at':datetime.now(timezone.utc).isoformat(),'latitude':latitude,'longitude':longitude,
                'source':'https://api.open-meteo.com/v1/forecast','payload':response.json()}
