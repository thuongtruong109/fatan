import geocoder

def get_location():
    g = geocoder.ip('me')
    if g.ok and g.latlng:
        return {
            "lat": g.latlng[0],
            "long": g.latlng[1],
            "city": g.city,
            "state": g.state,
            "country": g.country
        }
    return {
        "lat": None,
        "long": None,
        "city": None,
        "state": None,
        "country": None
    }