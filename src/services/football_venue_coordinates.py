"""Secondary coordinate evidence; never infer a venue from a team.

Exact stadium name, city AND postal code must agree with the event's ESPN venue.
This is a community survey, not an official roof-state confirmation.
"""
import csv
import io
import math
import hashlib

SOURCE='https://raw.githubusercontent.com/greerreNFL/Stadiums/main/data/stadiums.csv'


async def dataset(client):
    response=await client.get(SOURCE);response.raise_for_status()
    return list(csv.DictReader(io.StringIO(response.text))),hashlib.sha256(response.content).hexdigest()


def match(venue, rows, year):
    address=venue.get('address') or {}
    name=str(venue.get('fullName') or '').strip().casefold()
    city=str(address.get('city') or '').strip().casefold()
    postal=str(address.get('zipCode') or '').strip()
    if not name or not city or not postal:return None
    matches=[r for r in rows if r.get('stadium_name','').strip().casefold()==name
        and r.get('city','').strip().casefold()==city and r.get('zipcode','').strip()==postal]
    if len(matches)!=1:return None
    row=matches[0]
    try:
        if row.get('closed') and float(row['closed'])<=year:return None
        lat,lon=float(row['lat']),float(row['lon'])
        if not all(math.isfinite(v) for v in (lat,lon)) or not(-90<=lat<=90 and -180<=lon<=180):return None
    except (ValueError,KeyError):return None
    # Roof designation is contextual secondary evidence, not event confirmation.
    return {'latitude':lat,'longitude':lon,'roof':'unknown','survey_roof':row.get('roof_type'),
            'source':SOURCE,'source_row':row,'verification':'secondary_exact_name_city_postal_match'}
